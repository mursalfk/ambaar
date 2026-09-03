# Changelog

Notable changes per release. Format follows [Keep a Changelog](https://keepachangelog.com/1.1.0/);
versions follow [SemVer](https://semver.org/).

## [Unreleased]

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