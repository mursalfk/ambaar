<!-- CHANGELOG.md -->
# Changelog

Notable changes per release. Format follows [Keep a Changelog](https://keepachangelog.com/1.1.0/);
versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Changed
- Staged flow. A pasted link is checked first and added as Ready; downloading
  starts only when you press Download. Rows are tagged VIDEO or PLAYLIST.
- Rows carry inline icon buttons that follow the job's state (download, pause,
  resume, cancel, retry, open folder, options, remove), each with a tooltip,
  replacing the header-only controls. The header keeps the whole-list actions;
  the rest moved under a More menu so no button is clipped at narrow widths.
- A pasted link is added to the list immediately, on paste, Enter, the Add
  button, or when focus leaves the bar. Typing alone never adds half a URL.
  The bar's button is now labelled Add; Download belongs to the row.
- Double-click plays a finished video in the default player, opens the folder
  for a playlist, and starts a Ready row.
- Build scripts stop a running ambaar before building and no longer upgrade
  PySide6 implicitly.

### Added
- Options on each Ready row: quality ceiling, codec (H.264, VP9, AV1),
  container, audio-only, and a per-item output folder. Choices are limited to
  what the video offers.
- Playlist item picker: take 3 of 40 videos.
- Disk-space check before a download starts, per destination folder.
- Duplicate detection against the queue, the download archive and history.
- History page: searchable record of finished downloads that outlives the queue.
- Clipboard watcher (off by default) offering to add copied video links.
- Automatic retry with backoff for network failures, with a visible countdown.
- Drag rows to reorder the queue; order is saved.
- Keyboard shortcuts and a Queue menu.
- Per-item log, and Download again.
- Real Pause and Resume, keeping the partial file. Pause all, Resume all, and
  aggregate speed and count in the status bar.
- Thumbnails in the queue.
- Queue persistence in SQLite; interrupted downloads return as Paused.
- Desktop notification when a download finishes, with a Settings toggle.
- Clear queue.

### Fixed
- A playlist added while the global playlist setting was off saved its videos
  loose in the output folder and fetched only the first one.
- Links stuck on Resolving and Cancel being ignored during metadata lookup;
  resolving now has a socket timeout and an interrupt point.

## [1.1.0]

First public release.

### Added
- Download queue with painted rows: status marks, live speed, size, and time
  remaining. Cancel, retry, and clear finished.
- Self-verifying engine updater. Checks weekly, probes the new engine against a
  real media URL, and restores the previous version on regression.
- Packaged builds update their engine by unpacking the yt-dlp wheel to the user
  data directory, since a frozen app has no pip.
- ffmpeg detection with one-click install on Windows and Linux.
- JavaScript runtime (Deno) detection with one-click install. Without one,
  yt-dlp cannot solve YouTube's nsig challenge and silently returns fewer
  formats.
- Error diagnosis mapping yt-dlp failures to the thing that needs fixing.
- Python version preflight. Below 3.9, pip installs an obsolete yt-dlp instead
  of refusing; the app now says so rather than letting you chase a phantom bug.
- Audio extraction, subtitle embedding, thumbnail cover art, playlist support,
  browser cookie import, rate limiting, download archive.
- Windows taskbar identity via AppUserModelID, so the taskbar shows the app
  icon rather than the Python logo.
- Scheduler files for launchd, systemd, and Task Scheduler.
- `packaging/doctor.py` for environment diagnostics.
- Regression tests for version comparison, rate parsing, error diagnosis, and
  the rollback decision.
- CI builds Windows, macOS (Apple silicon and Intel), and Linux, launches each
  artifact to confirm it starts, and publishes to a GitHub Release.

### Fixed
- Qt was trimmed too aggressively in packaged builds, producing an app that
  packaged cleanly and then failed with `DLL load failed while importing
  QtCore`. Qt now ships whole by default; trimming is opt-in via `AMBAAR_LEAN=1`.
- The Engine page reported "yt_dlp already imported; managed engine not
  applied" regardless of the true state, because it re-ran the path resolver
  just to read a label. The result is now captured once at startup.
- CI targeted the `macos-13` runner, retired by GitHub in December 2025. Jobs
  queued forever waiting for a runner that no longer exists. Now on
  `macos-15-intel`.

### Known issues
- macOS builds are unsigned; Gatekeeper blocks the first launch. Right-click and
  Open, or `xattr -dr com.apple.quarantine "Ambaar.app"`.
- `AMBAAR_LEAN=1` produces a build that will not start. One entry in
  `QT_EXCLUDES` removes a DLL Qt still links against; the culprit is not yet
  isolated.
- The queue is in memory only and does not survive a restart.

[Unreleased]: https://github.com/mursalfk/ambaar/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/mursalfk/ambaar/releases/tag/v1.1.0