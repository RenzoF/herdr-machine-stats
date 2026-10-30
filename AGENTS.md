# herdr-machine-stats

Herdr plugin: live CPU, memory, disk and agent status for this machine and
every machine in `herdr machine list`, with btop drill-down and opt-in
deploy of itself to those machines.

- `bin/machine-stats`: curses front end. Run as `python3 bin/machine-stats`.
- `statslib/collect.py`: the POSIX collector script and polling;
  `render.py`: cards and the status legend; `deploy.py`: plugin state
  and installs; `config.py`: the `deploy`, `deploy_exclude`,
  `pipeline_url` and `secret_request_dir` settings; `pipeline.py`: the
  optional pipeline card's `/status` read; `herdr.py`: the only module
  that names the `herdr` CLI.
- Needs-you list: `needs.py` (items and order), `prompts.py` (secret
  requests, metadata only), `seen.py` (first-seen times, local only),
  `text.py` (cleaning and cell widths), `needsview.py` (drawing),
  `jump.py` (Enter). Spec: `docs/specs/2026-10-27-needs-you-design.md`.
- Python 3.11+, standard library only.
- Tests: `uv run --with pytest --with flake8 python -m pytest -q`;
  flake8 at 79 columns is enforced by `tests/test_lint.py`.
- Reads are read-only. The only changes ever made on another machine
  are this plugin, by an explicit deploy, and focusing a pane when you
  press Enter in the needs-you list. The pipeline card only GETs a URL.
