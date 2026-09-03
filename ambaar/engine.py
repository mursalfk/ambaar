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
from dataclasses import dataclass, asdict, field
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from . import ffmpeg as ffmpeg_tool
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


class Cancelled(Exception):
    """Raised inside the progress hook to unwind a running download."""


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


def build_opts(settings: Settings, hooks: dict) -> dict:
    outdir = Path(settings.output_dir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    if settings.playlist:
        tmpl = str(outdir / "%(playlist_title|Downloads)s" /
                   "%(playlist_index|)s%(playlist_index& - |)s%(title)s [%(id)s].%(ext)s")
    else:
        tmpl = str(outdir / "%(title)s [%(id)s].%(ext)s")

    opts: dict = {
        "outtmpl": tmpl,
        "noplaylist": not settings.playlist,
        "ignoreerrors": settings.playlist,
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

    opts["format"] = QUALITY_MAP.get(settings.quality, QUALITY_MAP["Best available"])
    opts["merge_output_format"] = settings.container

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
# Job model
# --------------------------------------------------------------------------- #

@dataclass
class Job:
    url: str
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    status: str = "Queued"
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    size: str = ""
    filepath: str = ""
    error: str = ""


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


# --------------------------------------------------------------------------- #
# Worker
# --------------------------------------------------------------------------- #

class WorkerSignals(QObject):
    started = Signal(str)                       # job_id
    progress = Signal(str, float, str, str, str)  # job_id, pct, speed, eta, size
    status = Signal(str, str)                   # job_id, status text
    title = Signal(str, str)                    # job_id, resolved title
    finished = Signal(str, str)                 # job_id, filepath
    failed = Signal(str, str)                   # job_id, error
    cancelled = Signal(str)                     # job_id
    log = Signal(str)                           # free-form log line


class _QuietLogger:
    """Routes yt-dlp's internal logging into the GUI log pane."""

    def __init__(self, emit):
        self._emit = emit

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            return
        if msg.strip():
            self._emit(msg)

    def info(self, msg: str) -> None:
        if msg.strip():
            self._emit(msg)

    def warning(self, msg: str) -> None:
        self._emit(f"Warning: {msg}")

    def error(self, msg: str) -> None:
        self._emit(f"Error: {msg}")


class DownloadWorker(QRunnable):
    def __init__(self, job: Job, settings: Settings):
        super().__init__()
        self.job = job
        self.settings = settings
        self.signals = WorkerSignals()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    # -- hooks (worker thread) ---------------------------------------------- #

    def _progress_hook(self, d: dict) -> None:
        if self._cancel:
            raise Cancelled()

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
            self.signals.status.emit(self.job.job_id, "Processing")

    def _pp_hook(self, d: dict) -> None:
        if self._cancel:
            raise Cancelled()
        if d.get("status") == "started":
            name = str(d.get("postprocessor", "")).replace("FFmpeg", "")
            self.signals.status.emit(self.job.job_id, f"Processing ({name})")

    # -- run ----------------------------------------------------------------- #

    @Slot()
    def run(self) -> None:
        self.signals.started.emit(self.job.job_id)
        self.signals.status.emit(self.job.job_id, "Resolving")

        hooks = {
            "progress": self._progress_hook,
            "postprocessor": self._pp_hook,
            "logger": _QuietLogger(self.signals.log.emit),
        }

        try:
            opts = build_opts(self.settings, hooks)
        except OSError as e:
            self.signals.failed.emit(self.job.job_id, f"Cannot use output folder: {e}")
            return

        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.job.url, download=False)
                if self._cancel:
                    raise Cancelled()
                if info:
                    if info.get("_type") == "playlist":
                        title = info.get("title") or "Playlist"
                        count = len(info.get("entries") or [])
                        self.signals.title.emit(self.job.job_id, f"{title} ({count} items)")
                    else:
                        self.signals.title.emit(self.job.job_id, info.get("title") or self.job.url)

                self.signals.status.emit(self.job.job_id, "Downloading")
                result = ydl.extract_info(self.job.url, download=True)

            path = ""
            if isinstance(result, dict):
                path = result.get("requested_downloads", [{}])[0].get("filepath", "") \
                    if result.get("requested_downloads") else ""
            self.signals.finished.emit(self.job.job_id, path)

        except Cancelled:
            self.signals.cancelled.emit(self.job.job_id)
        except DownloadError as e:
            self.signals.failed.emit(self.job.job_id, diagnose(str(e)))
        except Exception as e:  # noqa: BLE001 - a worker must never take down the app
            self.signals.failed.emit(self.job.job_id, f"{type(e).__name__}: {e}")


class DownloadManager(QObject):
    """Owns the thread pool and the set of live workers."""

    def __init__(self, settings: Settings, parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max(1, settings.max_parallel_jobs))
        self.workers: dict[str, DownloadWorker] = {}

    def submit(self, job: Job) -> DownloadWorker:
        worker = DownloadWorker(job, self.settings)
        self.workers[job.job_id] = worker
        self.pool.start(worker)
        return worker

    def cancel(self, job_id: str) -> None:
        worker = self.workers.get(job_id)
        if worker:
            worker.cancel()

    def cancel_all(self) -> None:
        for worker in self.workers.values():
            worker.cancel()

    def release(self, job_id: str) -> None:
        self.workers.pop(job_id, None)

    def set_parallelism(self, n: int) -> None:
        self.pool.setMaxThreadCount(max(1, n))
