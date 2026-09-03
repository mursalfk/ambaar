"""
Self-verifying yt-dlp updater.

The point of this module is NOT "pip install -U yt-dlp on a timer". Anyone can do
that, and it will happily install a build that is broken for your use case.

The flow here is:

    1. Probe the CURRENT install and record whether it works.
    2. Check the release channel for a newer version.
    3. Install it.
    4. Probe again -- in a fresh subprocess, because the running process still has
       the old yt_dlp module loaded in sys.modules.
    5. If the probe regressed (was working, now isn't), roll back to the previous
       version and record the failure.

The probe is the important part. A version check tells you nothing about whether
signature/nsig deciphering still works. The only reliable signal is: resolve a
real media URL, then issue a ranged GET against it. A 403 there is the classic
signature-failure symptom, and it is completely invisible to `--version`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

Channel = Literal["stable", "nightly"]

from .paths import data_dir, engine_dir, is_frozen
from . import bootstrap

STATE_DIR = data_dir()
STATE_FILE = STATE_DIR / "updater-state.json"
LOG_FILE = STATE_DIR / "updater.log"

RELEASE_API = {
    "stable": "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
    "nightly": "https://api.github.com/repos/yt-dlp/yt-dlp-nightly-builds/releases/latest",
}

# "Me at the zoo" -- the first video uploaded to YouTube. Public, short, and
# about as close to permanently available as anything on the platform gets.
DEFAULT_PROBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

# yt-dlp requires 3.9+. On an older interpreter pip resolves `yt-dlp` to the
# last compatible release instead of refusing, so you end up pinned to a stale
# engine that cannot decipher current players -- and the version number gives
# no hint. This is the usual cause of "nsig extraction failed".
MIN_PYTHON = (3, 9)

# PyPI JSON, used by frozen builds that cannot run pip.
PYPI_API = "https://pypi.org/pypi/yt-dlp/json"

UPDATE_INTERVAL = timedelta(days=7)
NETWORK_TIMEOUT = 30
PROBE_TIMEOUT = 120


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #

@dataclass
class ProbeResult:
    ok: bool
    stage: str          # "import" | "extract" | "fetch" | "done"
    detail: str
    version: str = ""
    http_status: int | None = None
    format_id: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ProbeResult":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class UpdaterState:
    last_check: str | None = None          # ISO 8601 UTC
    last_success: str | None = None
    installed_version: str = ""
    channel: Channel = "stable"
    probe_url: str = DEFAULT_PROBE_URL
    last_probe_ok: bool | None = None
    last_probe_detail: str = ""
    rollbacks: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls) -> "UpdaterState":
        if not STATE_FILE.is_file():
            return cls()
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in allowed})

    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        # Keep the file from growing without bound.
        self.history = self.history[-40:]
        self.rollbacks = self.rollbacks[-20:]
        STATE_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def due(self, interval: timedelta = UPDATE_INTERVAL) -> bool:
        if not self.last_check:
            return True
        try:
            last = datetime.fromisoformat(self.last_check)
        except ValueError:
            return True
        return _now() - last >= interval

    def next_check(self, interval: timedelta = UPDATE_INTERVAL) -> datetime | None:
        if not self.last_check:
            return None
        try:
            return datetime.fromisoformat(self.last_check) + interval
        except ValueError:
            return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now().isoformat(timespec="seconds")


def log(message: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{_stamp()}] {message}"
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Version discovery
# --------------------------------------------------------------------------- #

def python_ok() -> bool:
    return sys.version_info[:2] >= MIN_PYTHON


def python_problem() -> str:
    """Explanation if the interpreter is too old for yt-dlp, else ''."""
    if python_ok():
        return ""
    have = ".".join(str(x) for x in sys.version_info[:3])
    need = ".".join(str(x) for x in MIN_PYTHON)
    return (
        f"Python {have} is below yt-dlp's minimum of {need}. pip installs an "
        f"obsolete yt-dlp rather than refusing, so the engine cannot decipher "
        f"current YouTube players. Symptoms: 'nsig extraction failed', "
        f"'Falling back to generic n function search', 'Only images are "
        f"available'. Rebuild the environment on Python {need} or newer; no "
        f"yt-dlp update can fix this."
    )


def installed_version() -> str:
    """Version of yt-dlp in the CURRENT process. May be stale after an upgrade."""
    try:
        import yt_dlp.version
        return yt_dlp.version.__version__
    except Exception:
        return ""


def installed_version_fresh() -> str:
    """Version as seen by a fresh interpreter -- accurate after an in-place upgrade."""
    code = "import yt_dlp.version;print(yt_dlp.version.__version__)"
    try:
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=NETWORK_TIMEOUT,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (subprocess.SubprocessError, OSError):
        return ""


def latest_version(channel: Channel = "stable") -> str:
    """Latest published tag for the channel, or '' if the API is unreachable."""
    req = urllib.request.Request(
        RELEASE_API[channel],
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ambaar-updater",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        log(f"release check failed ({channel}): {e}")
        return ""
    tag = str(data.get("tag_name", "")).strip()
    return tag.lstrip("v")


def _version_key(v: str) -> tuple:
    """yt-dlp versions are date-based (2024.08.06, 2024.08.06.232819). Compare numerically."""
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) if parts else (0,)


def is_newer(candidate: str, current: str) -> bool:
    if not candidate:
        return False
    if not current:
        return True
    return _version_key(candidate) > _version_key(current)


# --------------------------------------------------------------------------- #
# The probe -- runs in a subprocess so it always sees the on-disk module
# --------------------------------------------------------------------------- #

_PROBE_SOURCE = textwrap.dedent(
    '''
    import json, sys, urllib.request, urllib.error

    url = sys.argv[1]
    out = {"ok": False, "stage": "import", "detail": "", "version": "",
           "http_status": None, "format_id": ""}

    try:
        from yt_dlp import YoutubeDL
        import yt_dlp.version
        out["version"] = yt_dlp.version.__version__
    except Exception as e:
        out["detail"] = "cannot import yt_dlp: %s" % e
        print(json.dumps(out)); sys.exit(0)

    out["stage"] = "extract"
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "noplaylist": True, "socket_timeout": 20}
    try:
        with YoutubeDL(opts) as ydl:
            # Drop the player cache so we exercise a real extraction, not a
            # cached signature function from a previous run.
            try:
                ydl.cache.remove()
            except Exception:
                pass
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        out["detail"] = "extraction failed: %s" % e
        print(json.dumps(out)); sys.exit(0)

    if not info:
        out["detail"] = "extractor returned no info"
        print(json.dumps(out)); sys.exit(0)

    formats = [f for f in (info.get("formats") or []) if f.get("url")]
    if not formats:
        out["detail"] = "no formats carried a resolved URL"
        print(json.dumps(out)); sys.exit(0)

    # Prefer a progressive or adaptive HTTPS format; skip HLS/DASH manifests,
    # which do not exercise the signature path the same way.
    def usable(f):
        return (f.get("protocol") or "").startswith("http") and f.get("url", "").startswith("http")

    candidates = [f for f in formats if usable(f)] or formats
    fmt = candidates[-1]
    out["format_id"] = str(fmt.get("format_id", ""))

    out["stage"] = "fetch"
    headers = dict(fmt.get("http_headers") or {})
    headers["Range"] = "bytes=0-2047"
    req = urllib.request.Request(fmt["url"], headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            out["http_status"] = resp.status
            chunk = resp.read(2048)
        if not chunk:
            out["detail"] = "media URL returned an empty body"
            print(json.dumps(out)); sys.exit(0)
    except urllib.error.HTTPError as e:
        out["http_status"] = e.code
        if e.code == 403:
            out["detail"] = "403 on media URL -- signature/nsig deciphering is broken"
        else:
            out["detail"] = "HTTP %s on media URL" % e.code
        print(json.dumps(out)); sys.exit(0)
    except Exception as e:
        out["detail"] = "media fetch failed: %s" % e
        print(json.dumps(out)); sys.exit(0)

    out["ok"] = True
    out["stage"] = "done"
    out["detail"] = "resolved format %s, fetched %d bytes (HTTP %s)" % (
        out["format_id"], len(chunk), out["http_status"])
    print(json.dumps(out))
    '''
)


def probe(url: str = DEFAULT_PROBE_URL) -> ProbeResult:
    """Verify end-to-end that the installed yt-dlp can produce a fetchable media URL."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE_SOURCE, url],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(False, "extract", f"probe timed out after {PROBE_TIMEOUT}s")
    except OSError as e:
        return ProbeResult(False, "import", f"could not launch probe: {e}")

    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return ProbeResult(False, "import", f"probe produced no output; stderr: {proc.stderr[:400]}")
    try:
        result = ProbeResult.from_dict(json.loads(line[-1]))
    except json.JSONDecodeError:
        return ProbeResult(False, "import", f"unparseable probe output: {line[-1][:400]}")

    # A failure on an unsupported interpreter almost always traces back to the
    # stale yt-dlp pip was forced to install. Say so, rather than leaving the
    # user to chase an nsig error that no update will resolve.
    if not result.ok and not python_ok():
        result.detail = f"{result.detail}  |  Root cause: {python_problem()}"
    return result


# --------------------------------------------------------------------------- #
# Installation
# --------------------------------------------------------------------------- #

def pip_install(spec: str, force: bool = False) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    if force:
        cmd.append("--force-reinstall")
    cmd += ["-U", spec]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return False, "pip timed out"
    except OSError as e:
        return False, f"could not run pip: {e}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-600:]
        return False, tail.strip()
    return True, "installed"


def latest_version_pypi() -> str:
    """Latest yt-dlp on PyPI. Used by frozen builds, which cannot run pip."""
    req = urllib.request.Request(PYPI_API, headers={"User-Agent": "ambaar"})
    try:
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as resp:
            data = json.load(resp)
        return str(data["info"]["version"])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, OSError) as e:
        log(f"pypi lookup failed: {e}")
        return ""


def wheel_url(version: str) -> str:
    """Locate the pure-Python wheel for a given yt-dlp release."""
    req = urllib.request.Request(f"https://pypi.org/pypi/yt-dlp/{version}/json",
                                 headers={"User-Agent": "ambaar"})
    try:
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        log(f"wheel lookup failed: {e}")
        return ""
    for entry in data.get("urls", []):
        if entry.get("packagetype") == "bdist_wheel" and entry.get("filename", "").endswith("-py3-none-any.whl"):
            return str(entry.get("url", ""))
    return ""


def install_wheel(version: str) -> tuple[bool, str]:
    """
    Unpack a yt-dlp wheel into the managed engine directory.

    yt-dlp is pure Python, so a wheel is just a zip that needs extracting
    somewhere importable -- no compiler, no pip, no site-packages write access.
    bootstrap.prepare_engine_path() puts the result ahead of the bundled copy on
    the next launch.
    """
    import shutil
    import tempfile
    import zipfile

    url = wheel_url(version)
    if not url:
        return False, f"No pure-Python wheel published for yt-dlp {version}"

    target = engine_dir() / version
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "yt_dlp.whl"
            req = urllib.request.Request(url, headers={"User-Agent": "ambaar"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(path, "wb") as fh:
                shutil.copyfileobj(resp, fh)

            staging = Path(tmp) / "x"
            with zipfile.ZipFile(path) as zf:
                zf.extractall(staging)

            if not (staging / "yt_dlp" / "__init__.py").is_file():
                return False, "Wheel did not contain a yt_dlp package"

            # Extract to a staging dir, then swap. A half-written engine
            # directory would be worse than no update at all.
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging), str(target))
    except (urllib.error.URLError, TimeoutError, zipfile.BadZipFile, OSError) as e:
        return False, f"Wheel install failed: {e}"

    return True, f"unpacked to {target}"


def channel_spec(channel: Channel, version: str = "") -> str:
    if channel == "nightly":
        base = "yt-dlp[default]"
        return f"{base}=={version}" if version else "--pre yt-dlp[default]"
    return f"yt-dlp=={version}" if version else "yt-dlp"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

@dataclass
class UpdateOutcome:
    action: str          # "up-to-date" | "updated" | "rolled-back" | "failed" | "skipped"
    message: str
    from_version: str = ""
    to_version: str = ""
    probe: ProbeResult | None = None


def run_update(
    state: UpdaterState | None = None,
    *,
    force: bool = False,
    verify_only: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> UpdateOutcome:
    """
    Full check-update-verify-rollback cycle.

    force        run even if the weekly interval has not elapsed
    verify_only  probe the current install and report; never install anything
    on_progress  optional callback for UI status lines
    """
    state = state or UpdaterState.load()

    def say(msg: str) -> None:
        log(msg)
        if on_progress:
            on_progress(msg)

    # Preflight. An unsupported interpreter is not something updating can fix,
    # and attempting it yields a pip resolver error instead of the diagnosis.
    problem = python_problem()
    if problem:
        say(f"Preflight failed: {problem}")
        state.last_check = _stamp()
        state.last_probe_ok = False
        state.last_probe_detail = problem
        state.history.append({"at": _stamp(), "action": "blocked",
                              "version": installed_version(), "probe_ok": False})
        state.save()
        return UpdateOutcome("blocked", problem, from_version=installed_version())

    if not force and not verify_only and not state.due():
        nxt = state.next_check()
        return UpdateOutcome("skipped", f"Not due yet (next check {nxt:%Y-%m-%d} )" if nxt else "Not due yet")

    current = installed_version_fresh() or installed_version()
    state.installed_version = current
    state.last_check = _stamp()

    say(f"Verifying current install (yt-dlp {current or 'unknown'})...")
    before = probe(state.probe_url)
    say(f"  {'OK' if before.ok else 'FAIL'}: {before.detail}")

    if verify_only:
        state.last_probe_ok = before.ok
        state.last_probe_detail = before.detail
        state.save()
        return UpdateOutcome(
            "up-to-date" if before.ok else "failed",
            before.detail, from_version=current, to_version=current, probe=before,
        )

    frozen = is_frozen()
    say(f"Checking {state.channel} channel for a newer release...")
    # Frozen builds track PyPI: they install wheels, so the wheel index is the
    # authoritative list of what they can actually get.
    latest = latest_version_pypi() if frozen else latest_version(state.channel)

    if not latest:
        state.last_probe_ok = before.ok
        state.last_probe_detail = before.detail
        state.save()
        return UpdateOutcome("failed", "Could not reach the release API.",
                             from_version=current, probe=before)

    if not is_newer(latest, current):
        state.last_probe_ok = before.ok
        state.last_probe_detail = before.detail
        if before.ok:
            state.last_success = _stamp()
        state.history.append({"at": _stamp(), "action": "up-to-date",
                              "version": current, "probe_ok": before.ok})
        state.save()
        msg = f"Already on the latest release ({current})."
        if not before.ok:
            msg += f" Warning: verification failed -- {before.detail}"
        return UpdateOutcome("up-to-date", msg, from_version=current,
                             to_version=current, probe=before)

    say(f"Updating {current or 'none'} to {latest} ...")
    if frozen:
        ok, detail = install_wheel(latest)
        if ok:
            bootstrap.set_active_engine(latest)
    else:
        ok, detail = pip_install(channel_spec(state.channel, latest))
    if not ok:
        state.save()
        return UpdateOutcome("failed", f"Install failed: {detail}",
                             from_version=current, to_version=latest, probe=before)

    new_version = installed_version_fresh()
    say(f"Installed {new_version}. Verifying...")
    after = probe(state.probe_url)
    say(f"  {'OK' if after.ok else 'FAIL'}: {after.detail}")

    # Roll back only on a genuine regression. If it was already broken before the
    # update, the new build is no worse -- keep it, since a fix may be imminent.
    if not after.ok and before.ok:
        say(f"Regression detected. Rolling back to {current} ...")
        if frozen:
            # Point back at the previous unpacked engine if we still have it,
            # otherwise drop to the copy baked into the bundle.
            previous = bootstrap.engine_dir() / current
            if (previous / "yt_dlp" / "__init__.py").is_file():
                bootstrap.set_active_engine(current)
                rb_ok, rb_detail = True, f"reactivated {current}"
            else:
                bootstrap.clear_active_engine()
                rb_ok, rb_detail = True, "fell back to the bundled engine"
        else:
            rb_ok, rb_detail = pip_install(channel_spec(state.channel, current), force=True)
        state.rollbacks.append({
            "at": _stamp(), "from": current, "to": new_version,
            "reason": after.detail, "restored": rb_ok, "restore_detail": rb_detail,
        })
        state.installed_version = installed_version_fresh()
        state.last_probe_ok = before.ok
        state.last_probe_detail = f"rolled back after failed update: {after.detail}"
        state.history.append({"at": _stamp(), "action": "rolled-back",
                              "version": state.installed_version, "probe_ok": before.ok})
        state.save()
        return UpdateOutcome(
            "rolled-back",
            f"{new_version} failed verification ({after.detail}). "
            f"{'Restored ' + current + '.' if rb_ok else 'Rollback ALSO failed: ' + rb_detail}",
            from_version=current, to_version=new_version, probe=after,
        )

    if frozen:
        bootstrap.prune_engines(keep=2)
    state.installed_version = new_version
    state.last_probe_ok = after.ok
    state.last_probe_detail = after.detail
    if after.ok:
        state.last_success = _stamp()
    state.history.append({"at": _stamp(), "action": "updated",
                          "version": new_version, "probe_ok": after.ok})
    state.save()

    msg = f"Updated {current or 'none'} -> {new_version}."
    if not after.ok:
        msg += f" Verification still failing: {after.detail}"
    return UpdateOutcome("updated", msg, from_version=current,
                         to_version=new_version, probe=after)


# --------------------------------------------------------------------------- #
# CLI entry point -- this is what cron / launchd / Task Scheduler calls
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="ambaar-updater",
        description="Update yt-dlp, verify it still works, roll back if it does not.",
    )
    p.add_argument("--force", action="store_true", help="Run even if not due")
    p.add_argument("--verify-only", action="store_true", help="Probe only; never install")
    p.add_argument("--channel", choices=["stable", "nightly"],
                   help="Release channel to track (persisted)")
    p.add_argument("--probe-url", help="Video URL used for verification (persisted)")
    p.add_argument("--status", action="store_true", help="Print stored state and exit")
    args = p.parse_args(argv)

    state = UpdaterState.load()

    if args.status:
        print(json.dumps(asdict(state), indent=2))
        return 0

    if args.channel:
        state.channel = args.channel
    if args.probe_url:
        state.probe_url = args.probe_url

    outcome = run_update(state, force=args.force, verify_only=args.verify_only,
                         on_progress=lambda m: print(m, flush=True))
    print(f"\n{outcome.action.upper()}: {outcome.message}")
    return 0 if outcome.action in {"updated", "up-to-date", "skipped"} else 1


if __name__ == "__main__":
    sys.exit(main())
