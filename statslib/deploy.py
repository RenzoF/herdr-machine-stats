"""Deploying this plugin to the machines it watches.

Nothing here runs unless the user turned deploy on. The only command sent
to another machine is ``herdr plugin install`` for this plugin, pinned to
the commit this machine runs.
"""

import os
import shlex
import subprocess
import threading

from statslib import REPO

STATES = ("current", "older", "newer", "missing", "unknown")
DEPLOY_TIMEOUT = 120
REMOTE_PATH = "PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin"


class Refused(Exception):
    """Deploying would send code that is not published. Message: why."""


def version_key(text):
    """``"0.2.0"`` as ``(0, 2, 0)``; None when it is not dotted integers."""
    try:
        return tuple(int(part) for part in text.split("."))
    except (AttributeError, ValueError):
        return None


def plugin_state(local_version, entry):
    """current, older, newer, missing or unknown, for a remote ``entry``."""
    if entry is None:
        return "unknown"
    if not entry:
        return "missing"
    remote = version_key(entry.get("version", ""))
    here = version_key(local_version)
    if remote is None or here is None:
        return "unknown"
    if remote == here:
        return "current"
    return "older" if remote < here else "newer"


def linked(entry):
    """True when ``entry`` is a local checkout linked into Herdr."""
    return bool(entry) and (entry.get("source") or {}).get("kind") == "local"


def deployable(state, entry):
    """Whether deploy may install on a machine in ``state``."""
    return state in ("missing", "older") and not linked(entry)


def run_git(root, *args):
    """stdout of ``git -C root args``; a failure raises Refused.

    git never reads the terminal, which the dashboard reads keys from,
    and never prompts for credentials.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            timeout=60, stdin=subprocess.DEVNULL,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused(f"git {args[0]} failed: {exc}") from exc
    if done.returncode:
        lines = done.stderr.strip().splitlines()
        raise Refused(f"git {args[0]} failed: "
                      f"{lines[0] if lines else done.returncode}")
    return done.stdout.strip()


def source_commit(entry, git=run_git):
    """The commit to deploy, from this machine's own plugin ``entry``."""
    if not entry:
        raise Refused("this machine has no installed copy to deploy from")
    source = entry.get("source") or {}
    if source.get("kind") == "github":
        commit = source.get("resolved_commit")
        if not commit:
            raise Refused("this copy records no GitHub commit")
        return commit
    if source.get("kind") != "local":
        raise Refused(f"unknown plugin source {source.get('kind')!r}")
    root = entry["plugin_root"]
    if git(root, "status", "--porcelain"):
        raise Refused("this copy has uncommitted changes")
    commit = git(root, "rev-parse", "HEAD")
    git(root, "fetch", "--quiet", "origin")
    if not git(root, "branch", "-r", "--contains", commit):
        raise Refused(f"{commit[:12]} is not on GitHub; push it first")
    return commit


def install_argv(target, commit):
    """The SSH command that installs ``commit`` of this plugin on target."""
    script = (f"{REMOTE_PATH}; herdr plugin install {REPO} "
              f"--ref {commit} --yes")
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            target, "sh -c " + shlex.quote(script)]


def auto_targets(rows, targets, local_version, attempted):
    """(label, target) pairs auto mode should deploy to now.

    ``rows`` and ``targets`` are parallel and start with this machine,
    which is never a target; ``attempted`` holds labels already tried
    this run.
    """
    picks = []
    for row, target in zip(rows[1:], targets[1:]):
        if row.label in attempted or row.snapshot is None:
            continue
        entry = row.snapshot.plugin
        if deployable(plugin_state(local_version, entry), entry):
            picks.append((row.label, target))
    return picks


class Deployer:
    """Installs in the background, at most one at a time per machine."""

    def __init__(self, run=None, timeout=DEPLOY_TIMEOUT):
        self.run = run or subprocess.run
        self.timeout = timeout
        self.lock = threading.Lock()
        self.status = {}
        self.threads = {}

    def start(self, label, target, commit):
        """Begin installing on ``target``; False if one is running."""
        with self.lock:
            if self.status.get(label) == "deploying...":
                return False
            self.status[label] = "deploying..."
        thread = threading.Thread(
            target=self._install, args=(label, target, commit), daemon=True)
        self.threads[label] = thread
        thread.start()
        return True

    def _install(self, label, target, commit):
        try:
            done = self.run(install_argv(target, commit), capture_output=True,
                            text=True, timeout=self.timeout,
                            stdin=subprocess.DEVNULL)
            if done.returncode:
                lines = (done.stderr or done.stdout or "").strip().splitlines()
                result = "failed: " + (
                    lines[0] if lines else f"exit {done.returncode}")
            else:
                result = "deployed"
        except subprocess.TimeoutExpired:
            result = "failed: timeout"
        except OSError as exc:
            result = f"failed: {exc}"
        with self.lock:
            self.status[label] = result

    def get(self, label):
        with self.lock:
            return self.status.get(label)
