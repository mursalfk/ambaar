<!-- README.md -->
<p align="center">
  <img src="assets/brand/lockup-dark.png" alt="Ambaar" width="440">
</p>

<p align="center">
  <em>anbaar</em> — Urdu and Sindhi for a stockpile, a heap.<br>
  <em>ambar</em> — amber. The name and the accent colour are the same word twice.
</p>

<p align="center">
  A desktop download manager whose engine verifies itself.
</p>

---

Most downloaders break a few weeks after you install them. YouTube changes its
player, the bundled engine goes stale, and nothing tells you — downloads just
start failing, or quietly return a worse file than you asked for.

Ambaar checks weekly, proves the new engine can still fetch real media before
trusting it, and rolls back automatically when it cannot.

---

## Download

No Python needed. Unzip and run.

| Platform             | File                      |
| -------------------- | ------------------------- |
| Windows 10/11        | `ambaar-windows.zip`      |
| macOS, Apple silicon | `ambaar-macos-arm64.zip`  |
| macOS, Intel         | `ambaar-macos-x86_64.zip` |
| Linux, x86_64        | `ambaar-linux.tar.gz`     |

Get the latest from the **Releases** page.

**macOS:** the build is unsigned, so Gatekeeper blocks the first launch.
Right-click the app and choose Open, or run
`xattr -dr com.apple.quarantine "Ambaar.app"`.

**Linux:** run `packaging/linux/install-desktop-entry.sh` after extracting so
the launcher picks up the icon.

---

## Using it

### Your first download

1. Copy a video or playlist link.
2. Paste it into the bar. There is no second step: the link leaves the bar and
   becomes a row in the list, marked Resolving while Ambaar checks it. The
   **Paste** button does the same from the clipboard, and **Add** (or Enter)
   adds a link you typed. Clicking away from the bar adds it too.
3. When the check finishes the row becomes Ready, with a **VIDEO** or
   **PLAYLIST** tag, a thumbnail, and its title. Nothing downloads yet.
4. Press the download icon on the row, or **Download all** in the header.

Paste several links at once, separated by spaces or commas; each becomes its
own row. A link that is not a video or playlist is rejected with the reason.
Text that is not a link is left in the bar for you to fix, and only Enter or
**Add** tells you it was not a link. A playlist downloads every item into its
own folder.

**ffmpeg is required** for anything above 360p. On first run Ambaar detects
whether you have it and offers a one-click install on Windows and Linux; on
macOS use `brew install ffmpeg`. This matters more than it sounds: YouTube
serves video and audio as separate streams above 360p, so without ffmpeg
downloads *appear* to succeed while silently giving you a low-quality single
stream.

### Reading the queue

Each row carries a thumbnail, a status mark, the title, a VIDEO or PLAYLIST
tag, and live metrics. The marks are shapes rather than colours alone, so the
queue stays readable if you cannot separate the ember from the green. States
that share a shape are told apart by the status word beside it.

| Mark           | State       | Meaning                                                  |
| -------------- | ----------- | -------------------------------------------------------- |
| square         | Ready       | checked and waiting for you to press Download            |
| square         | Queued      | waiting for a free slot, or for a retry countdown        |
| square         | Paused      | stopped; partial file kept, press Resume                 |
| arrow          | Resolving   | checking the link, no bytes yet                          |
| arrow          | Downloading | transferring; the hairline at the row's base is progress |
| rotated square | Processing  | ffmpeg is merging, converting, or embedding              |
| check          | Done        | finished                                                 |
| cross          | Failed      | the second line explains why                             |
| dash           | Cancelled   | stopped by you                                           |

Icon buttons sit at the right of each row and change with its state. Rest the
pointer on one to see its name.

| State                         | Icons                                                |
| ----------------------------- | ---------------------------------------------------- |
| Resolving, Queued, Processing | Cancel                                               |
| Ready                         | Download, Options, Remove (playlists also get Items) |
| Downloading                   | Pause, Cancel                                        |
| Paused                        | Resume, Cancel                                       |
| Done                          | Open folder, Remove                                  |
| Failed, Cancelled             | Retry, Remove                                        |

The header keeps the actions that cover the whole list: **Download all**,
**Pause all**, **Resume all**, and a **More** menu holding Cancel selected,
Retry selected, Clear finished and Clear queue.

**Double-click a row** to act on it: a finished video plays in your default
player, a finished playlist opens its folder, and a Ready row starts.
Right-click shows the same actions as the buttons.

**Pause** keeps the partial file and **Resume** continues from it, even after
you close the app. **Pause all** and **Resume all** act on the whole queue, and
the status bar shows the total speed and remaining count.

The queue is saved. Close Ambaar mid-download and the row returns as Paused;
Ready rows stay Ready. Desktop notifications announce finished downloads and can
be turned off in Settings.

Retrying a failed or cancelled row resumes from its partial file rather than
starting over.

### Choosing what to download

**Options** on a Ready row sets that one item's format and folder without
touching your global settings: quality ceiling, codec (H.264, VP9 or AV1),
container, audio-only, and a **Save to** folder. The quality and codec lists
show only what the video actually offers. Quality is a ceiling and a codec is a
preference, so a video with no AV1 stream still downloads at its best.

**Items** on a playlist row lists every video with a checkbox, so you can take
3 of 40. The row then reads "3 of 40 items".

Before a download starts, Ambaar compares its estimated size with the free space
on the destination drive and asks before going ahead if it looks short. The
estimate is approximate, so it is a question, not a refusal.

### Keeping track

**Duplicates.** Adding a link that is already in the queue, in your download
archive, or in your history asks first. Different forms of the same link
(`youtu.be`, `watch?v=`, shorts, tracking suffixes) count as the same video.

**History** keeps everything that finished, after you remove the row from the
queue. Search it, open the file or folder, or add a link again.

**Clipboard.** Turn on *Offer to add video links I copy* in Settings and copying
a YouTube, Vimeo, TikTok or similar link shows a one-line offer above the queue.
It is off by default and never adds anything on its own.

**Automatic retries.** Network failures are retried after 15 seconds, 1 minute,
then 5 minutes, up to the number set in Settings (0 turns it off). The row shows
the countdown and Cancel stops it. Failures that will not fix themselves, such
as a private video, a stale engine or a full disk, are not retried.

**Per-item log.** Right-click a row and choose *View log* to see exactly what the
engine did for that item. *Download again* replaces a finished file.

**Reorder** by dragging rows. The order decides what *Download all* starts first
and is saved with the queue.

### Keyboard

| Key                    | Does                                                               |
| ---------------------- | ------------------------------------------------------------------ |
| Ctrl+Shift+V           | add the link on the clipboard                                      |
| Ctrl+L                 | focus the link bar                                                 |
| Ctrl+1 to 5            | go to Queue, History, Settings, Engine, Activity                   |
| Ctrl+Shift+D / P / R   | download all / pause all / resume all                              |
| Space                  | on selected rows: pause, resume, download or retry, whichever fits |
| Enter                  | open a finished item, or start a Ready one                         |
| Delete                 | remove selected rows that are not running                          |
| Ctrl+V (queue focused) | add the link on the clipboard                                      |

### Settings worth knowing

**Quality** caps resolution rather than forcing it — pick 1080p and a 720p
source still downloads at 720p. **Best available** takes the highest on offer.

**Container** is the wrapper. `mp4` has the widest compatibility; `mkv` handles
odd codec combinations without re-encoding and is the better choice if a merge
ever fails.

**Audio only** extracts to mp3, m4a, opus, flac, or wav. Pair it with **Embed
thumbnail** for cover art.

**Cookies from** is the fix for age-restricted, private, and members-only
videos. Choose a browser you are signed into and Ambaar borrows its session.
Nothing is uploaded; the cookies are read locally and passed to the engine.

**Parallel downloads** is how many videos run at once. **Fragment threads** is
how many pieces of a *single* video download simultaneously. Raising the second
speeds up one large file; raising the first helps a long queue. Both at maximum
will saturate a home connection.

**Skip anything already downloaded** keeps a record of finished video IDs and
passes over them on later runs. Useful for re-running a playlist to catch only
what is new.

**Speed limit** accepts `2M` or `500K`. Leave it blank for unlimited.

### The Engine section

The badge in the sidebar footer is engine health at a glance: green verified,
red failing, grey not yet checked. Click it to open the section.

**Check for updates** fetches a newer engine, verifies it, and rolls back on
regression. **Verify only** tests what you have without installing anything —
run this first whenever downloads start failing.

Verification is not a version check. It resolves a real media URL and issues a
ranged request against it, because a version number tells you nothing about
whether the engine still works.

### When a download fails

The second line of a failed row names the cause in plain language. The common
ones:

| What you see                       | What to do                                         |
| ---------------------------------- | -------------------------------------------------- |
| Format not available / only images | Engine is stale. Engine section, Check for updates |
| 403 on the media URL               | Same — signature deciphering broke                 |
| Sign in to confirm                 | Set **Cookies from** to a signed-in browser        |
| Video unavailable                  | The video is gone. Not fixable here                |
| An ffmpeg step failed              | Engine section, Install ffmpeg                     |

Full engine output lives in the **Activity** section.

---

## Run from source

```bash
git clone <your-repo-url> ambaar
cd ambaar

python3 -m venv .venv          # Windows: py -3.12 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
                               # Git Bash: source .venv/Scripts/activate

pip install -r requirements.txt
python main.py
```

Python 3.9 or newer is mandatory. Below that, pip installs an obsolete yt-dlp
instead of refusing; Ambaar detects this and says so rather than letting you
chase a phantom bug.

---

## Releasing it

You do not build the `.exe` by hand for every release. Tag a version and GitHub
builds all four platforms and publishes them:

```bash
git tag v1.1.0
git push origin v1.1.0
```

The workflow builds on real Windows, macOS, and Linux runners, **launches each
built app to confirm it starts**, and attaches the artifacts to a GitHub
Release. Users download from that page; nothing is required of them but unzip
and run.

Cross-compiling is not possible — a Windows `.exe` can only be produced on
Windows — which is exactly why the matrix exists.

### What a user actually downloads

`ambaar-windows.zip`, containing `ambaar.exe` and the libraries beside it. They
extract the folder and double-click the `.exe`. This is the normal shape for a
PyInstaller app and what most desktop software does.

If you would rather hand out a **single file** with nothing beside it:

```powershell
$env:AMBAAR_ONEFILE=1
pyinstaller packaging\ambaar.spec --noconfirm --clean
```

That yields one `ambaar.exe` with everything inside. Two real costs: it unpacks
to a temp directory on every launch, so startup is several seconds slower, and
antivirus heuristics flag self-extracting executables far more aggressively —
including SmartScreen warnings on an unsigned binary. For a download link on
your site, the zip is the safer default.

### Building locally

```bash
powershell -ExecutionPolicy Bypass -File packaging/build.ps1   # Windows
./packaging/build.sh                                           # macOS, Linux
```

Output lands in `dist/`. Always pass `--clean` when invoking PyInstaller
directly; it caches aggressively and will reproduce a bug you already fixed.

### If the packaged build fails to start

Run the doctor first:

```bash
python packaging/doctor.py
```

**"DLL load failed while importing QtCore"** is the common one, and the wording
matters. *Module* could not be found means a DLL is missing — install the
Microsoft VC++ 2015-2022 redistributable. *Procedure* could not be found means
a DLL was found but is the wrong version, which is a packaging fault rather than
a Qt fault.

If `python main.py` runs fine and only the packaged build fails, the cause is
almost always Qt being trimmed too far. Qt now ships whole by default, so this
should not recur. Should you set `AMBAAR_LEAN=1` to shrink the download, launch
the result before shipping it — the failure is invisible at build time.

## How the engine updater works

This is the part worth understanding, because the obvious version of it is
worse than useless.

**What it does not do:** scrape YouTube's player and regenerate signature
deciphering logic. `nsig` is obfuscated JavaScript whose structure changes, not
just its constants. yt-dlp ships a JavaScript interpreter and a team watching
for breakage to handle it. A homegrown solver would fail constantly and
silently.

**What it does:** treat every engine update as a change that must prove itself.

```
1. probe the current install          record pass or fail
2. check the release channel          is there something newer?
3. install it
4. probe again, fresh subprocess      the running process still holds the
                                      old module in sys.modules
5. worked before, fails now?          restore the previous version
```

Step 4 is load-bearing. The probe resolves a real media URL and issues a ranged
GET against it. **A 403 there is the signature of broken signature
deciphering** — the exact failure `--version` cannot see.

Rollback is deliberately conservative: it fires only on a *regression*. If the
engine was already broken before the update, the newer build is kept, because
fixes come forward rather than backward. And since rollback requires
`before.ok and not after.ok`, a network outage cannot trigger a spurious revert
— both probes fail and nothing moves.

### Packaged builds update differently

A packaged app has no pip and no writable site-packages, so `pip install -U`
cannot work. Without a fix, every download would be frozen against whatever
yt-dlp existed on build day — precisely the failure this project exists to
prevent.

yt-dlp is pure Python, so a newer release does not need installing, it needs
unpacking somewhere importable. The updater downloads the wheel, extracts it to
the user data directory, and `bootstrap.py` puts that ahead of the bundled copy
on `sys.path`. The bundled engine remains as a fallback, so a corrupt download
degrades to "older engine" rather than "app will not start".

### Scheduling

Two layers, and you want both:

- **In-app** — checks on launch if more than seven days have passed. Zero
  setup, but only runs when you open the app.
- **OS-level** — the files in `scheduler/`. Edit the paths, then follow the
  install comments at the top of each. All three catch up if the machine was
  asleep at the scheduled time, which is how weekly jobs usually die unnoticed.

Point the scheduler at the **virtualenv's** interpreter, not the system one.
Otherwise it updates yt-dlp in the wrong site-packages, reports success, and the
app keeps running the old engine — a silent failure with no visible symptom
until a download breaks weeks later.

```bash
python -m ambaar.updater --status    # confirm it actually fired
```

---

## CLI

```bash
python -m ambaar.updater --force          # check, update, verify
python -m ambaar.updater --verify-only    # probe only, never install
python -m ambaar.updater --status         # dump stored state
python -m ambaar.updater --channel nightly
python packaging/doctor.py                # environment diagnostics
```

---

## Replacing the Python icon on Windows

Setting a window icon is the obvious half. The half that catches everyone is
that on Windows it is not enough: you set the icon, the title bar shows it, and
the taskbar still shows the Python logo.

The taskbar groups buttons by **AppUserModelID**, not by window icon. A script
launched through `python.exe` inherits Python's AUMID, so the shell decides the
running program is Python and draws Python's icon. `ambaar/branding.py` fixes it
in one call, made before any window exists:

```python
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("dev.mursalfk.ambaar")
```

Ordering matters. After the first window is created Windows has already assigned
the grouping and the call is silently ignored.

Three icons, three places:

| What                   | Set by                                        |
| ---------------------- | --------------------------------------------- |
| Title bar and alt-tab  | `app.setWindowIcon()` in `branding.apply()`   |
| Taskbar button         | the AppUserModelID call, plus the window icon |
| The `.exe` in Explorer | `icon=` in `packaging/ambaar.spec`            |

Regenerate after any change to the mark:

```bash
python packaging/make_logo.py     # SVG source of truth, plus PNG renders
python packaging/make_icons.py    # per-size PNGs, .ico, .icns on macOS
```

---

## Where things live

| Path                                                                         | Contents                                         |
| ---------------------------------------------------------------------------- | ------------------------------------------------ |
| `ambaar/app.py`                                                              | main window, sidebar, queue                      |
| `ambaar/engine.py`                                                           | settings, jobs, worker threads, error diagnosis  |
| `ambaar/updater.py`                                                          | update, verify, roll back; also a CLI            |
| `ambaar/bootstrap.py`                                                        | engine path resolution for packaged builds       |
| `ambaar/branding.py`                                                         | window icon and Windows taskbar identity         |
| `ambaar/theme.py`                                                            | every colour, font, and metric in the app        |
| `ambaar/widgets.py`                                                          | painted marks, row delegate, empty state         |
| `ambaar/store.py`                                                            | SQLite queue and history                         |
| `ambaar/links.py`                                                            | link keys, duplicate detection, clipboard filter |
| `ambaar/space.py`                                                            | size estimates and the disk-space check          |
| `ambaar/formatdialog.py`, `itemsdialog.py`, `logdialog.py`, `historypage.py` | per-item options, playlist picker, log, history  |
| `ambaar/thumbs.py`                                                           | thumbnail cache                                  |
| `ambaar/ffmpeg.py`                                                           | ffmpeg discovery and download                    |
| `ambaar/paths.py`                                                            | per-user data locations                          |

State lives in the platform data directory — `%APPDATA%\ambaar` on Windows,
`~/Library/Application Support/ambaar` on macOS, `~/.local/share/ambaar` on
Linux. Set `AMBAAR_HOME` to override.

---

## Design notes

**Threading.** yt-dlp is blocking, so each job runs on a `QRunnable` in a
`QThreadPool`. Progress hooks fire on the worker thread and leave it as Qt
signals, which Qt queues onto the GUI thread. No widget is touched from a
worker. The updater gets its own single-slot pool, so a wheel unpack never
contends with downloads.

**Cancellation.** yt-dlp has no cooperative cancel API, so the progress hook
raises to unwind the download. Partial files stay on disk and resume on retry.

**Painting.** Queue rows are drawn by a `QStyledItemDelegate` rather than
composed from widgets. Every mark — status marks, combo chevrons, spin
steppers, the empty-state icon, the app icon — is a stroked path. Partly a
design rule, partly practical: glyph icons assume the user has a font that
ships them, which is exactly what breaks on a clean Windows install.

**Typography.** Space Grotesk and DM Mono when present, with fallback stacks
otherwise. Drop the files into `assets/fonts/`; see the README there.

---

## Scope

Fine for your own uploads, Creative Commons material, and offline personal use.
Bulk redistribution of other people's content is a different question, and
YouTube's terms restrict downloading without permission. Be deliberate about
what you point this at.

## License

MIT. See `LICENSE`.