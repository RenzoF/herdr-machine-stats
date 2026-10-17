# herdr-machine-stats

Herdr plugin: live CPU, memory, disk and agent status for this machine and
every machine in `herdr machine list`, with btop drill-down and opt-in
deploy of itself to those machines.

- `bin/machine-stats`: curses front end. Run as `python3 bin/machine-stats`.
- `statslib/collect.py`: the POSIX collector script and polling;
  `render.py`: cards; `deploy.py`: plugin state and installs;
  `config.py`: the `deploy` setting; `herdr.py`: the only module that
  names the `herdr` CLI.
- Python 3.11+, standard library only.
- Tests: `uv run --with pytest --with flake8 python -m pytest -q`;
  flake8 at 79 columns is enforced by `tests/test_lint.py`.
- Reads are read-only. The only thing ever written to another machine is
  this plugin, by an explicit deploy.
