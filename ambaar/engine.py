# ambaar/engine.py
"""
Download engine: settings model + cancellable yt-dlp workers on a Qt thread pool.

Threading notes
---------------
yt-dlp is synchronous and blocking, so each job runs on a QRunnable in a
QThreadPool. Progress hooks fire on the worker thread; every update leaves that
thread as a Qt signal, which Qt queues onto the GUI thread automatically. No
widget is ever touched from a worker.

Cancellation works by raising from inside the progress hook -- yt-dlp has no
cooperative cancel API, so an exception is the supported way out. Partial files
are left on disk and `continuedl` resumes them on the next attempt.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict, field, replace
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from . import ffmpeg as ffmpeg_tool
from . import jsruntime, space, thumbs
from .paths import data_dir, default_download_dir

CONFIG_FILE = data_dir() / "settings.json"

QUALITY_MAP = {
    "Best available": "bestvideo*+bestaudio/best",
    "2160p (4K)": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "1440p": "bestvideo[height<=1440]+bestaudio/best[height<=1440]",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
}


CONTAINERS = ["mp4", "mkv", "webm"]
CODECS = ["any", "h264", "vp9", "av1"]
CODEC_LABEL = {"any": "Any codec", "h264": "H.264", "vp9": "VP9", "av1": "AV1"}
_CODEC_PREFIX = {"h264": "avc1", "vp9": "vp9", "av1": "av01"}
# yt-dlp reports VP9 as "vp09.00..." on YouTube and plain "vp9" elsewhere, so a
# plain prefix match would miss one of them.
_CODEC_FILTER = {"h264": "[vcodec~='^(avc1|h264)']",
                 "vp9": "[vcodec~='^(vp9|vp09)']",
                 "av1": "[vcodec~='^av01']"}
AUDIO_FORMATS = ["mp3", "m4a", "opus", "flac", "wav"]


# --------------------------------------------------------------------------- #
# Per-item format choice
# --------------------------------------------------------------------------- #
#
# A row can override the global Quality / Container / Audio settings. The choice
# is stored as one short string so it fits a single database column and a
# single Job attribute:
#
#     ""                    follow the settings
#     "video|1080p|mp4"     video at most 1080p, mp4 container
#     "audio|mp3"           audio only, mp3
#
# Anything that does not parse is treated as "follow the settings", so a
# hand-edited or future-format value can never stop a download.

def encode_format(audio: bool, quality: str = "", container: str = "",
                  audio_format: str = "", codec: str = "any") -> str:
    if audio:
        return f"audio|{audio_format}" if audio_format in AUDIO_FORMATS else ""
    if quality in QUALITY_MAP and container in CONTAINERS:
        base = f"video|{quality}|{container}"
        return f"{base}|{codec}" if codec in _CODEC_PREFIX else base
    return ""


def decode_format(choice: str) -> dict:
    """Parsed choice as {"audio": bool, ...}, or {} when it means 'defaults'."""
    parts = (choice or "").split("|")
    if parts[0] == "audio" and len(parts) == 2 and parts[1] in AUDIO_FORMATS:
        return {"audio": True, "audio_format": parts[1]}
    if (parts[0] == "video" and len(parts) in (3, 4)
            and parts[1] in QUALITY_MAP and parts[2] in CONTAINERS):
        codec = parts[3] if len(parts) == 4 else "any"
        if codec not in _CODEC_PREFIX and codec != "any":
            return {}
        return {"audio": False, "quality": parts[1], "container": parts[2],
                "codec": codec}
    return {}


def apply_format(settings: "Settings", choice: str) -> "Settings":
    """A copy of `settings` with the per-item choice laid over it."""
    d = decode_format(choice)
    if not d:
        return settings
    if d["audio"]:
        return replace(settings, audio_only=True, audio_format=d["audio_format"])
    return replace(settings, audio_only=False, quality=d["quality"],
                   container=d["container"], codec=d["codec"])


def describe_format(choice: str) -> str:
    """Short label for a row, or "" when the row follows the settings."""
    d = decode_format(choice)
    if not d:
        return ""
    if d["audio"]:
        return f"{d['audio_format'].upper()} audio"
    quality = d["quality"].split(" ")[0]
    label = f"{quality} {d['container'].upper()}"
    if d["codec"] != "any":
        label += f" {CODEC_LABEL[d['codec']]}"
    return label


def video_format(quality: str, codec: str = "any") -> str:
    """
    yt-dlp format selector for a quality ceiling and codec preference.

    A codec is a preference, not a requirement: the selector falls back to the
    plain quality choice rather than failing when the video has no such stream.
    """
    base = QUALITY_MAP.get(quality, QUALITY_MAP["Best available"])
    match = _CODEC_FILTER.get(codec)
    if not match:
        return base
    lead = quality.split("p")[0]
    cap = f"[height<={lead}]" if lead.isdigit() else ""
    return f"bestvideo{cap}{match}+bestaudio/{base}"


class Cancelled(Exception):
    """Raised from a hook to unwind a running download for good."""


class Paused(Exception):
    """
    Raised from a hook to unwind a download that should resume later.

    Same mechanism as Cancelled -- yt-dlp has no cooperative stop API, so an
    exception is the supported way out of a blocking call. The difference is
    only in what happens afterwards: the .part file is kept either way, but a
    paused job stays in the list with a Resume button.
    """


# yt-dlp's error text is accurate but rarely names the cause. These map the
# common failures onto the thing that actually needs fixing, most specific
# first. Plain ASCII only: this text is also written to log files.
_DIAGNOSES: list[tuple[tuple[str, ...], str]] = [
    (
        ("nsig extraction failed", "generic n function search",
         "only images are available", "requested format is not available"),
        "Cause: format URLs could not be deciphered, so every real format was "
        "stripped and only storyboard images survived. The engine is stale. "
        "Open the Engine section and run a check. If it reports a Python "
        "problem, fix that first -- pip installs an obsolete yt-dlp on Python "
        "3.8 rather than refusing outright.",
    ),
    (
        ("http error 403", "403: forbidden"),
        "Cause: 403 on the media URL, which means signature deciphering is "
        "broken. Open the Engine section and run a check.",
    ),
    (
        ("sign in to confirm", "age-restricted", "private video",
         "members-only", "join this channel"),
        "Cause: this video needs an account. Set 'Cookies from' in Settings to "
        "a browser you are signed in to.",
    ),
    (
        ("video unavailable", "removed by the uploader",
         "not available in your country", "this video is unavailable"),
        "Cause: the video itself is unavailable. Not a downloader fault.",
    ),
    (
        ("ffmpeg", "ffprobe", "postprocessing"),
        "Cause: an ffmpeg step failed. Check the Engine section -- ffmpeg can "
        "be installed from there.",
    ),
    (
        ("no space left", "disk full", "not enough space", "errno 28"),
        "Cause: the drive is full. Free some space or choose another output "
        "folder in Settings; the partial file is kept and resumes afterwards.",
    ),
    (
        ("unable to download webpage", "connection", "timed out",
         "temporary failure", "network is unreachable"),
        "Cause: network problem reaching YouTube. Check connectivity, retry.",
    ),
]


def diagnose(message: str) -> str:
    """Append a plain-language cause where we recognise the failure."""
    low = message.lower()
    for needles, explanation in _DIAGNOSES:
        if any(n in low for n in needles):
            return f"{message}\n\n{explanation}"
    return message


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

@dataclass
class Settings:
    output_dir: str = ""   # resolved on load; see Settings.load
    quality: str = "Best available"
    container: str = "mp4"
    audio_only: bool = False
    audio_format: str = "mp3"
    embed_thumbnail: bool = True
    embed_subs: bool = False
    sub_langs: str = "en"
    auto_subs: bool = False
    playlist: bool = False
    concurrency: int = 4
    max_parallel_jobs: int = 2
    limit_rate: str = ""            # "2M", "500K", or empty
    cookies_from_browser: str = ""  # "", "chrome", "firefox", ...
    archive_enabled: bool = False
    notify_on_finish: bool = True
    codec: str = "any"              # "any", "h264", "vp9", "av1"; set per item
    auto_retry: int = 3             # automatic retries for transient failures; 0 is off
    watch_clipboard: bool = False
    restore_queue: bool = True
    update_channel: str = "stable"
    auto_update: bool = True

    @classmethod
    def load(cls) -> "Settings":
        if not CONFIG_FILE.is_file():
            return cls(output_dir=str(default_download_dir()))
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        allowed = {f for f in cls.__dataclass_fields__}
        s = cls(**{k: v for k, v in raw.items() if k in allowed})
        if not s.output_dir:
            s.output_dir = str(default_download_dir())
        return s

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass


def parse_rate(text: str) -> int | None:
    text = (text or "").strip().upper()
    if not text:
        return None
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    try:
        if text[-1] in mult:
            return int(float(text[:-1]) * mult[text[-1]])
        return int(float(text))
    except ValueError:
        return None


def build_opts(settings: Settings, hooks: dict, playlist: bool | None = None) -> dict:
    outdir = Path(settings.output_dir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    # `playlist` is the resolved kind of this link; None falls back to the
    # global setting. Without it a playlist added while that setting is off
    # would land loose in the output folder instead of in its own.
    as_playlist = settings.playlist if playlist is None else playlist

    if as_playlist:
        tmpl = str(outdir / "%(playlist_title|Downloads)s" /
                   "%(playlist_index|)s%(playlist_index& - |)s%(title)s [%(id)s].%(ext)s")
    else:
        tmpl = str(outdir / "%(title)s [%(id)s].%(ext)s")

    opts: dict = {
        "outtmpl": tmpl,
        "noplaylist": not as_playlist,
        "ignoreerrors": as_playlist,
        "windowsfilenames": True,
        "continuedl": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": max(1, settings.concurrency),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "postprocessors": [],
        "progress_hooks": [hooks["progress"]],
        "postprocessor_hooks": [hooks["postprocessor"]],
        "logger": hooks["logger"],
    }

    # A downloaded ffmpeg is not on PATH, so point yt-dlp at it explicitly.
    ffmpeg_path, _ = ffmpeg_tool.find()
    if ffmpeg_path:
        opts["ffmpeg_location"] = str(ffmpeg_path.parent)

    # Same for a managed Deno. Rather than passing a path through js_runtimes
    # config -- whose accepted keys are not part of yt-dlp's documented API --
    # put the tools directory on PATH and let yt-dlp discover the runtime the
    # ordinary way. Fewer assumptions, and it survives yt-dlp changing the
    # shape of that config.
    if jsruntime.find():
        jsruntime.ensure_on_path()
        opts["js_runtimes"] = {"deno": {}}

    # No network operation may block forever. Without this a stalled connection
    # hangs the resolve phase indefinitely, holding a thread-pool slot and
    # taking the queue down with it.
    opts["socket_timeout"] = 30

    rate = parse_rate(settings.limit_rate)
    if rate:
        opts["ratelimit"] = rate

    if settings.cookies_from_browser:
        opts["cookiesfrombrowser"] = (settings.cookies_from_browser,)

    if settings.archive_enabled:
        opts["download_archive"] = str(Path.home() / ".ambaar" / "archive.txt")
        Path(opts["download_archive"]).parent.mkdir(parents=True, exist_ok=True)

    if settings.audio_only:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"].append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": settings.audio_format,
            "preferredquality": "0",
        })
        opts["postprocessors"].append({"key": "FFmpegMetadata"})
        if settings.embed_thumbnail:
            opts["writethumbnail"] = True
            opts["postprocessors"].append({"key": "EmbedThumbnail"})
        return opts

    opts["format"] = video_format(settings.quality, settings.codec)
    container = settings.container
    # H.264 cannot be muxed into webm; mkv holds it without re-encoding.
    if settings.codec == "h264" and container == "webm":
        container = "mkv"
    opts["merge_output_format"] = container

    if settings.embed_subs:
        langs = [s.strip() for s in settings.sub_langs.split(",") if s.strip()]
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = settings.auto_subs
        opts["subtitleslangs"] = langs or ["en"]
        opts["postprocessors"].append({
            "key": "FFmpegEmbedSubtitle", "already_have_subtitle": False,
        })

    opts["postprocessors"].append({"key": "FFmpegMetadata", "add_chapters": True})

    if settings.embed_thumbnail:
        opts["writethumbnail"] = True
        opts["postprocessors"].append({"key": "EmbedThumbnail"})

    return opts


# --------------------------------------------------------------------------- #
# Job model and state machine
# --------------------------------------------------------------------------- #
#
# A job moves through these states. Adding a link no longer starts a download:
# it stages the link, resolves it to confirm the link is real and to learn what
# it is, and then waits for the user to press Download.
#
#   Staged -> Resolving -> Ready -> Queued -> Downloading -> Processing -> Done
#                       \-> Failed        \-> Paused -^
#                                          \-> Cancelled
#
# The states are plain strings so they survive a round trip through JSON when
# the queue is persisted later. The sets below are the single source of truth
# for "is this job busy" and "which buttons does this row show"; scattering
# those decisions across the UI is how they drift apart.

STAGED = "Staged"
RESOLVING = "Resolving"
READY = "Ready"
QUEUED = "Queued"
DOWNLOADING = "Downloading"
PAUSED = "Paused"
PROCESSING = "Processing"
DONE = "Done"
FAILED = "Failed"
CANCELLED = "Cancelled"

# Occupying a thread, so cancellable and blocking a slot.
BUSY = {RESOLVING, QUEUED, DOWNLOADING, PROCESSING}
# Finished one way or another; safe to clear from the list.
TERMINAL = {DONE, FAILED, CANCELLED}
# Can be started or restarted by the user.
STARTABLE = {READY, PAUSED, FAILED, CANCELLED}

KIND_VIDEO = "video"
KIND_PLAYLIST = "playlist"
KIND_UNKNOWN = "unknown"


@dataclass
class Job:
    url: str
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    status: str = STAGED
    kind: str = KIND_UNKNOWN
    item_count: int = 0          # playlist entries; 0 for a single video
    duration: int = 0            # seconds; 0 when unknown
    uploader: str = ""
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    size: str = ""
    filepath: str = ""
    folder: str = ""             # where the file landed, for "Open folder"
    thumb: str = ""              # local cached image, "" when unavailable
    fmt: str = ""                # per-item format override; "" follows settings
    entries: str = ""            # playlist contents as JSON: [{"i":1,"t":"title","d":secs}]
    items: str = ""              # chosen playlist positions, e.g. "1-3,7"; "" is all
    sizes: str = ""              # format sizes for the space estimate (see space.py)
    dest: str = ""               # per-item output folder; "" follows settings
    # Session-only state, deliberately not persisted:
    redo: bool = False           # "download again": overwrite and ignore the archive
    attempts: int = 0            # automatic retries used so far
    log: list = field(default_factory=list)
    error: str = ""

    def is_playlist(self) -> bool:
        return self.kind == KIND_PLAYLIST


# --------------------------------------------------------------------------- #
# Playlist selection
# --------------------------------------------------------------------------- #
#
# Positions are yt-dlp's own 1-based playlist indices, so the spec can be handed
# straight to its `playlist_items` option. Unavailable entries (deleted or
# private videos) still occupy a position, which is why positions are recorded
# at resolve time rather than recomputed from a filtered list.

MAX_ENTRIES = 2000      # a row's worth of metadata must stay small enough to save


def pack_entries(raw: list) -> str:
    """Compact JSON of a flat playlist listing; None entries keep their slot."""
    out = []
    for pos, e in enumerate(raw[:MAX_ENTRIES], start=1):
        if not e:
            continue
        out.append({"i": pos,
                    "t": str(e.get("title") or e.get("id") or "")[:120],
                    "d": int(e.get("duration") or 0)})
    return json.dumps(out, separators=(",", ":"), ensure_ascii=False)


def unpack_entries(text: str) -> list[dict]:
    try:
        data = json.loads(text or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return [e for e in data if isinstance(e, dict) and isinstance(e.get("i"), int)] \
        if isinstance(data, list) else []


def compress_items(positions) -> str:
    """{1,2,3,7} -> "1-3,7". Empty input gives "" (callers treat that as all)."""
    nums = sorted({int(n) for n in positions if int(n) > 0})
    spans, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        spans.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(spans)


def expand_items(spec: str) -> set[int]:
    """Inverse of compress_items. Malformed pieces are skipped, not fatal."""
    out: set[int] = set()
    for part in (spec or "").split(","):
        part = part.strip()
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                out.update(range(int(a), int(b) + 1))
            elif part:
                out.add(int(part))
        except ValueError:
            continue
    return {n for n in out if n > 0}


def selected_positions(job: "Job") -> set[int]:
    """Positions that will download: the chosen ones, or every entry."""
    entries = unpack_entries(job.entries)
    everything = {e["i"] for e in entries}
    if not job.items:
        return everything
    chosen = expand_items(job.items)
    # Entries are known: ignore positions that no longer exist.
    return chosen & everything if everything else chosen


def selection_summary(job: "Job") -> tuple[int, int, int]:
    """(selected count, total count, selected duration in seconds)."""
    entries = unpack_entries(job.entries)
    if not entries:
        return job.item_count, job.item_count, job.duration
    chosen = selected_positions(job)
    return (len(chosen), len(entries),
            sum(e["d"] for e in entries if e["i"] in chosen))


MAX_LOG_LINES = 500


def append_log(job: "Job", text: str) -> None:
    """Add engine output to a job's own log, keeping only the newest lines."""
    for line in str(text).splitlines():
        if line.strip():
            job.log.append(line.rstrip())
    if len(job.log) > MAX_LOG_LINES:
        del job.log[:len(job.log) - MAX_LOG_LINES]


def output_dir_for(job: "Job", settings: "Settings") -> str:
    """Where this job writes: its own folder if it has one, else the default."""
    return job.dest or settings.output_dir


# --------------------------------------------------------------------------- #
# Automatic retry
# --------------------------------------------------------------------------- #

RETRY_DELAYS = (15, 60, 300)    # seconds before attempts 1, 2, 3 and later

# Failures worth waiting out. Everything else -- a private video, a stale
# engine, a full disk -- will fail identically however often it is retried, and
# retrying only delays the message the user needs to see.
_TRANSIENT = ("timed out", "timeout", "connection", "temporary failure",
              "network is unreachable", "http error 5", "http error 429",
              "too many requests", "incompleteread", "remote end closed",
              "reset by peer", "unable to download webpage", "ssl:")


def is_transient(error: str) -> bool:
    low = (error or "").lower()
    if "403" in low or "forbidden" in low:
        return False
    return any(n in low for n in _TRANSIENT)


def retry_delay(attempt: int) -> int:
    """Seconds to wait before the given 1-based retry attempt."""
    return RETRY_DELAYS[max(0, min(attempt - 1, len(RETRY_DELAYS) - 1))]


def should_retry(error: str, attempts: int, limit: int) -> bool:
    return limit > 0 and attempts < limit and is_transient(error)


def estimate_job_bytes(job: "Job", settings: "Settings") -> int:
    """
    Bytes still to download for a job, 0 when unknown.

    Uses real format sizes for a single video, a duration-based guess for a
    playlist, and subtracts what a paused job already has on disk.
    """
    eff = apply_format(settings, job.fmt)
    cap = None
    if not eff.audio_only:
        lead = eff.quality.split("p")[0]
        cap = int(lead) if lead.isdigit() else None

    if job.is_playlist():
        _, _, seconds = selection_summary(job)
        total = space.rough_estimate(seconds, cap, eff.audio_only)
    elif eff.audio_only:
        total = space.estimate_audio(job.sizes)
    else:
        total = space.estimate_video(job.sizes, cap)
    if total and job.percent and 0 < job.percent < 100:
        total = int(total * (1 - job.percent / 100))
    return total


def human_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "--"
    if n <= 0:
        return "--"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_eta(seconds) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "--"
    if s < 0:
        return "--"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def human_duration(seconds) -> str:
    """Runtime, written the way a video player writes it."""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# --------------------------------------------------------------------------- #
# Logger
# --------------------------------------------------------------------------- #

class _QuietLogger:
    """
    Routes yt-dlp's internal logging into the GUI log pane, and doubles as the
    interrupt point for phases where no progress hook fires.

    Progress hooks only fire once bytes are moving, so during
    extract_info(download=False) there is nothing to raise from. A job stuck
    resolving would hold its thread-pool slot forever and ignore Cancel -- and
    with only a couple of parallel slots, two stuck resolves wedge the whole
    queue. yt-dlp calls the logger steadily throughout extraction, so checking
    here gives those phases an interrupt point they otherwise lack.
    """

    def __init__(self, emit, interrupt=None):
        self._emit = emit
        self._interrupt = interrupt or (lambda: None)

    def _check(self) -> None:
        exc = self._interrupt()
        if exc is not None:
            raise exc

    def debug(self, msg: str) -> None:
        self._check()
        if msg.startswith("[debug] "):
            return
        if msg.strip():
            self._emit(msg)

    def info(self, msg: str) -> None:
        self._check()
        if msg.strip():
            self._emit(msg)

    def warning(self, msg: str) -> None:
        self._check()
        self._emit(f"Warning: {msg}")

    def error(self, msg: str) -> None:
        # Never raise from error(): yt-dlp calls it while unwinding its own
        # failures, and raising there would mask the real cause.
        self._emit(f"Error: {msg}")


# --------------------------------------------------------------------------- #
# Resolve worker
# --------------------------------------------------------------------------- #

class ResolveSignals(QObject):
    resolved = Signal(str, dict)   # job_id, facts
    failed = Signal(str, str)      # job_id, error
    cancelled = Signal(str)        # job_id
    log = Signal(str, str)         # job_id, line


class ResolveWorker(QRunnable):
    """
    Confirms a link is real and learns what it is, without downloading.

    Runs flat: playlist entries are listed rather than individually resolved,
    so a 200-video playlist comes back in about the time one video would. The
    user sees what they pasted before committing to a download.
    """

    def __init__(self, job: Job, settings: Settings):
        super().__init__()
        self.job = job
        self.settings = settings
        self.signals = ResolveSignals()
        self._cancel = False

    def _emit_log(self, line: str) -> None:
        self.signals.log.emit(self.job.job_id, line)

    def cancel(self) -> None:
        self._cancel = True

    def _interrupt(self):
        return Cancelled() if self._cancel else None

    @Slot()
    def run(self) -> None:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": False,      # classify first; the user chooses after
            "extract_flat": "in_playlist",
            "socket_timeout": 20,
            "retries": 3,
            "logger": _QuietLogger(self._emit_log, self._interrupt),
        }
        if self.settings.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.settings.cookies_from_browser,)

        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.job.url, download=False)
            if self._cancel:
                raise Cancelled()
            if not info:
                self.signals.failed.emit(self.job.job_id,
                                         "Nothing was found at that link.")
                return

            if info.get("_type") == "playlist":
                raw = list(info.get("entries") or [])
                entries = [e for e in raw if e]
                # A playlist has no picture of its own, so borrow the first
                # episode's -- which is what the platform itself shows.
                thumb_source = info if info.get("thumbnails") else (entries[0] if entries else {})
                facts = {
                    "kind": KIND_PLAYLIST,
                    "title": info.get("title") or "Playlist",
                    "item_count": len(entries),
                    "entries": pack_entries(raw),
                    "duration": sum(int(e.get("duration") or 0) for e in entries),
                    "uploader": info.get("uploader") or info.get("channel") or "",
                    "thumb_url": thumbs.pick(thumb_source or {}),
                }
            else:
                facts = {
                    "kind": KIND_VIDEO,
                    "title": info.get("title") or self.job.url,
                    "sizes": space.pack_sizes(info),
                    "item_count": 0,
                    "duration": int(info.get("duration") or 0),
                    "uploader": info.get("uploader") or info.get("channel") or "",
                    "thumb_url": thumbs.pick(info),
                }

            # Fetched here rather than at paint time: this thread is already
            # doing network work and the GUI thread must never block on a
            # download, however small.
            if not self._cancel:
                facts["thumb"] = thumbs.fetch(facts.get("thumb_url") or "")

            self.signals.resolved.emit(self.job.job_id, facts)

        except Cancelled:
            self.signals.cancelled.emit(self.job.job_id)
        except DownloadError as e:
            self.signals.failed.emit(self.job.job_id, diagnose(str(e)))
        except Exception as e:  # noqa: BLE001 - a worker must never kill the app
            self.signals.failed.emit(self.job.job_id, f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Download worker
# --------------------------------------------------------------------------- #

class WorkerSignals(QObject):
    started = Signal(str)                         # job_id
    progress = Signal(str, float, str, str, str)  # job_id, pct, speed, eta, size
    status = Signal(str, str)                     # job_id, status
    title = Signal(str, str)                      # job_id, resolved title
    finished = Signal(str, str)                   # job_id, filepath
    failed = Signal(str, str)                     # job_id, error
    cancelled = Signal(str)                       # job_id
    paused = Signal(str)                          # job_id
    log = Signal(str, str)         # job_id, line


class DownloadWorker(QRunnable):
    """
    Runs one download, interruptible two ways.

    Pause and cancel are the same mechanism -- unwind the blocking yt-dlp call
    by raising from a hook -- and differ only in what the GUI does afterwards.
    Both leave the .part file alone, so a paused job resumes from where it
    stopped; `continuedl` in build_opts is what makes the next attempt send a
    Range request rather than start over.
    """

    def __init__(self, job: Job, settings: Settings):
        super().__init__()
        self.job = job
        self.settings = settings
        self.signals = WorkerSignals()
        self._cancel = False
        self._pause = False

    def _emit_log(self, line: str) -> None:
        self.signals.log.emit(self.job.job_id, line)

    def cancel(self) -> None:
        self._cancel = True

    def pause(self) -> None:
        self._pause = True

    def _interrupt(self):
        """The exception this worker should unwind with, or None to carry on."""
        if self._cancel:
            return Cancelled()
        if self._pause:
            return Paused()
        return None

    # -- hooks (worker thread) ---------------------------------------------- #

    def _progress_hook(self, d: dict) -> None:
        exc = self._interrupt()
        if exc is not None:
            raise exc

        st = d.get("status")
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else 0.0
            self.signals.progress.emit(
                self.job.job_id,
                pct,
                f"{human_bytes(d.get('speed'))}/s" if d.get("speed") else "--",
                human_eta(d.get("eta")),
                f"{human_bytes(done)} / {human_bytes(total)}" if total else human_bytes(done),
            )
        elif st == "finished":
            self.signals.progress.emit(self.job.job_id, 100.0, "--", "--",
                                       human_bytes(d.get("total_bytes")))
            self.signals.status.emit(self.job.job_id, PROCESSING)

    def _pp_hook(self, d: dict) -> None:
        # Cancel still applies during post-processing, but pause does not: ffmpeg
        # cannot resume a half-written merge, so pausing here would mean redoing
        # the work. The button is hidden in this state for the same reason.
        if self._cancel:
            raise Cancelled()
        if d.get("status") == "started":
            name = str(d.get("postprocessor", "")).replace("FFmpeg", "")
            self.signals.status.emit(self.job.job_id, f"{PROCESSING} ({name})")

    # -- run ----------------------------------------------------------------- #

    @Slot()
    def run(self) -> None:
        self.signals.started.emit(self.job.job_id)
        self.signals.status.emit(self.job.job_id, DOWNLOADING)

        hooks = {
            "progress": self._progress_hook,
            "postprocessor": self._pp_hook,
            "logger": _QuietLogger(self._emit_log, self._interrupt),
        }

        try:
            settings = apply_format(self.settings, self.job.fmt)
            if self.job.dest:
                settings = replace(settings, output_dir=self.job.dest)
            opts = build_opts(settings, hooks, playlist=self.job.is_playlist())
        except OSError as e:
            self.signals.failed.emit(self.job.job_id, f"Cannot use output folder: {e}")
            return

        if self.job.redo:
            # "Download again" means exactly that: replace the file and ignore
            # the archive that would otherwise skip it as already downloaded.
            opts["overwrites"] = True
            opts.pop("download_archive", None)

        # The resolve step already classified this link, and `playlist=` above
        # makes build_opts honour that rather than the global setting. A partial
        # selection is passed through as yt-dlp's own item spec.
        if self.job.is_playlist() and self.job.items:
            opts["playlist_items"] = self.job.items

        try:
            with YoutubeDL(opts) as ydl:
                result = ydl.extract_info(self.job.url, download=True)

            path = ""
            if isinstance(result, dict):
                downloads = result.get("requested_downloads") or []
                if downloads:
                    path = downloads[0].get("filepath", "")
                elif result.get("_type") == "playlist":
                    # A playlist has no single file; point at the folder its
                    # first entry landed in so "Open folder" has a target.
                    for entry in (result.get("entries") or []):
                        if entry and entry.get("requested_downloads"):
                            path = entry["requested_downloads"][0].get("filepath", "")
                            break
            self.signals.finished.emit(self.job.job_id, path)

        except Paused:
            self.signals.paused.emit(self.job.job_id)
        except Cancelled:
            self.signals.cancelled.emit(self.job.job_id)
        except DownloadError as e:
            self.signals.failed.emit(self.job.job_id, diagnose(str(e)))
        except Exception as e:  # noqa: BLE001 - a worker must never kill the app
            self.signals.failed.emit(self.job.job_id, f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Manager
# --------------------------------------------------------------------------- #

class DownloadManager(QObject):
    """
    Owns both thread pools and every live worker.

    Resolve and download get separate pools on purpose. They shared one in the
    first version, which meant a couple of slow resolves could occupy every
    slot and stall downloads that were ready to run. Resolving is cheap and
    short, so its pool can be wider than the download pool.
    """

    RESOLVE_THREADS = 4

    def __init__(self, settings: Settings, parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings

        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max(1, settings.max_parallel_jobs))
        self.resolve_pool = QThreadPool()
        self.resolve_pool.setMaxThreadCount(self.RESOLVE_THREADS)

        self.workers: dict[str, DownloadWorker] = {}
        self.resolvers: dict[str, ResolveWorker] = {}

    # -- resolve ------------------------------------------------------------- #

    def resolve(self, job: Job) -> ResolveWorker:
        worker = ResolveWorker(job, self.settings)
        self.resolvers[job.job_id] = worker
        self.resolve_pool.start(worker)
        return worker

    def release_resolver(self, job_id: str) -> None:
        self.resolvers.pop(job_id, None)

    # -- download ------------------------------------------------------------ #

    # Higher numbers run first in a QThreadPool. A row's priority is this base
    # minus its position in the list, so the top of the queue runs first.
    PRIORITY_BASE = 10_000

    def submit(self, job: Job, position: int = 0) -> DownloadWorker:
        worker = DownloadWorker(job, self.settings)
        self._enqueue(job.job_id, worker, position)
        return worker

    def _enqueue(self, job_id: str, worker, position: int) -> None:
        self.workers[job_id] = worker
        self.pool.start(worker, self.PRIORITY_BASE - position)

    def apply_order(self, order: list[str]) -> int:
        """
        Re-rank downloads that are waiting for a slot to match the list order.

        Only jobs that have not started can move. `tryTake` pulls a runnable back
        out of the pool's queue and fails for one already running, which is
        exactly the distinction wanted: a download in progress is never
        disturbed, and one still waiting is resubmitted at its new rank.
        Returns how many were moved.
        """
        moved = 0
        for position, job_id in enumerate(order):
            worker = self.workers.get(job_id)
            if worker is not None and self.pool.tryTake(worker):
                self.pool.start(worker, self.PRIORITY_BASE - position)
                moved += 1
        return moved

    def pause(self, job_id: str) -> None:
        worker = self.workers.get(job_id)
        if worker:
            worker.pause()

    def cancel(self, job_id: str) -> None:
        """Stop whichever worker holds this job, resolving or downloading."""
        for registry in (self.workers, self.resolvers):
            worker = registry.get(job_id)
            if worker:
                worker.cancel()

    def cancel_all(self) -> None:
        for worker in list(self.workers.values()):
            worker.cancel()
        for worker in list(self.resolvers.values()):
            worker.cancel()

    def pause_all(self) -> None:
        for worker in list(self.workers.values()):
            worker.pause()

    def release(self, job_id: str) -> None:
        self.workers.pop(job_id, None)

    def set_parallelism(self, n: int) -> None:
        self.pool.setMaxThreadCount(max(1, n))
