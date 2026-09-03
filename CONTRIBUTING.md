# Contributing

Thanks for looking. This is a small project and the bar is low: if something is
broken or missing, an issue is welcome even without a patch.

## Getting set up

```bash
git clone https://github.com/mursalfk/ambaar
cd ambaar

python3 -m venv .venv          # Windows: py -3.12 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pytest

python main.py
pytest -q
```

**Python 3.9 is the floor and it is not negotiable.** Below it, pip installs an
obsolete yt-dlp instead of refusing, and you will spend a day debugging code
that is fine. `packaging/doctor.py` catches this and most other environment
problems.

## Where things live

| Path | What it does |
|---|---|
| `ambaar/app.py` | main window, sidebar, queue |
| `ambaar/engine.py` | settings, jobs, worker threads, error diagnosis |
| `ambaar/updater.py` | update, verify, roll back; also a CLI |
| `ambaar/bootstrap.py` | engine path resolution for packaged builds |
| `ambaar/branding.py` | window icon, Windows taskbar identity |
| `ambaar/theme.py` | every colour, font, and metric |
| `ambaar/widgets.py` | painted marks, row delegate, empty state |
| `ambaar/ffmpeg.py` `ambaar/jsruntime.py` | external tool discovery and install |
| `ambaar/paths.py` | per-user data locations |
| `packaging/doctor.py` | environment diagnostics |

## Things that will bite you

These are real bugs this project has already shipped and fixed. They are not
hypothetical.

**A build that compiles is not a build that runs.** Qt failures appear only when
the frozen app starts. `AMBAAR_LEAN=1` trims Qt and has produced a build that
packaged cleanly and then died with `DLL load failed while importing QtCore`.
If you touch the spec, launch the result.

**Verify in a subprocess, not in-process.** After updating yt-dlp, the running
interpreter still holds the old module in `sys.modules`. Checking in-process
tests the version you just replaced and reports a false pass.

**Do not call `prepare_engine_path()` to read a status string.** It must run
before yt_dlp is imported. Calling it later always reports "already imported"
regardless of the truth. Use `engine_source()`.

**Rollback fires only on regression.** The condition is `before.ok and not
after.ok`, deliberately. If both probes fail, that is usually a network outage,
and reverting would pin users to an ever-older engine. Do not "simplify" this
to `not after.ok`.

**Never touch a widget from a worker thread.** Workers emit Qt signals; Qt
queues them onto the GUI thread. Progress hooks run on the worker.

## Style

**Marks are drawn, never typed.** No arrow glyphs anywhere, including log and
error text. `widgets.py` has painters for chevrons, status marks, and steppers.
Glyph icons assume the user has a font that ships them, which is exactly what
breaks on a clean Windows install.

**No colour literals outside `theme.py`.** Zero border-radius throughout.

**Comments explain why, not what.** `# increment counter` is noise. `# fresh
subprocess: the running process still holds the old module` is the reason
someone will not undo your fix.

## Before opening a PR

```bash
pytest -q
python main.py                 # and actually download something
python packaging/doctor.py
```

If you touched packaging, build **and launch** the packaged app on your
platform. Say which platform in the PR.

New logic in `updater.py` or `engine.py` wants a test in `tests/test_logic.py`.
The suite is fast and has no network or Qt dependency; keep it that way.

## Reporting bugs

Use the issue templates. The Engine section's four lines (Version, Source, Last
checked, Verification) distinguish a stale engine from a real bug, and without
them the first reply is always going to be a request for them.

## Scope

Ambaar downloads media for personal use. Changes aimed at bulk redistribution,
circumventing paywalls, or evading platform restrictions are out of scope.

## Licence

MIT. Contributions are accepted under the same terms.