# herdr-machine-stats

Herdr plugin: live CPU, memory, disk and agent status for this machine and
every machine in `herdr machine list`, with btop drill-down and opt-in
deploy of itself to those machines.

- `bin/machine-stats`: curses front end. Run as `python3 bin/machine-stats`.
- `statslib/collect.py`: the POSIX collector script and polling;
  `render.py`: cards; `deploy.py`: plugin state and installs;
  `config.py`: the `deploy`, `deploy_exclude` and `pipeline_url` settings; `pipeline.py`:
  the optional pipeline card's `/status` read; `herdr.py`: the only module
  that names the `herdr` CLI.
- `app-mod/`: the same dashboard as a Herdr desktop app mod (JavaScript,
  gpui-kit), linked as `~/.config/herdr-app/mods/machine-stats`. Pure logic
  in `stats.js` (no `herdr` or `gpui-kit` imports, so Node tests it);
  `main.js` is the view. The app's `herdr.d.ts` and `gpui-kit.d.ts` in
  `~/.config/herdr-app` are the API's truth.
- Python 3.11+, standard library only. The mod's tests need Node 22+.
- Tests: `uv run --with pytest --with flake8 python -m pytest -q`;
  flake8 at 79 columns is enforced by `tests/test_lint.py`.
  `tests/test_app_mod.py` runs the Node suite (`node --test tests/js/`)
  and `herdr-app check` on the mod (plus seeded copies), each skipped
  where its tool is missing. Tests fake `exec` and `hc`, and checks run
  with a scratch `HERDR_APP_HOME` and `HC_SESSION`: never the live core.
- Reads are read-only. The only thing ever written to another machine is
  this plugin, by an explicit deploy. The pipeline card only GETs a URL.
