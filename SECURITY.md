# Security

## Reporting

Email **mursalfurqan@gmail.com** or open a [private advisory](https://github.com/mursalfk/ambaar/security/advisories/new).
Please do not open a public issue for anything exploitable.

Expect a reply within a week.

## What the app touches

Worth knowing if you are assessing risk:

- **Browser cookies.** With "Cookies from" set, yt-dlp reads that browser's
  cookie store to access age-restricted or private videos. Cookies are read
  locally and passed to the engine. Nothing is uploaded anywhere.
- **Network.** Ambaar contacts YouTube and other sites you give it, PyPI and
  GitHub for engine and tool updates, and the ffmpeg and Deno release hosts if
  you use the one-click installers. Nothing else.
- **Downloaded code.** The updater unpacks yt-dlp wheels from PyPI into the user
  data directory and adds it to `sys.path`. It runs with your privileges. This
  is what makes packaged builds updatable without pip, and it means a
  compromised PyPI package would run as you.
- **No telemetry.** Nothing is collected or transmitted about you or what you
  download.

## Scope

In scope: anything that lets a crafted URL, playlist, or downloaded file execute
code, escape the download directory, or read files it should not.

Out of scope: yt-dlp's own vulnerabilities (report those upstream), and the
unsigned macOS build triggering Gatekeeper, which is a known limitation rather
than a flaw.