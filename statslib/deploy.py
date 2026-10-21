"""Deploying this plugin to the machines it watches.

Nothing here runs unless the user turned deploy on. The only command sent
to another machine is ``herdr plugin install`` for this plugin, pinned to
the commit this machine runs.
"""

import os
import shlex
import subprocess
import threading
import time

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


def git_env():
    """The environment for git: nothing may prompt on the terminal.

    ``GIT_TERMINAL_PROMPT`` stops git's own credential prompts. A fetch
    over SSH runs ssh, which opens /dev/tty for a passphrase or an unknown
    host, so ssh is told never to ask; a ``GIT_SSH_COMMAND`` already set is
    kept and gains the option.
    """
    ssh = os.environ.get("GIT_SSH_COMMAND") or "ssh"
    return dict(os.environ, GIT_TERMINAL_PROMPT="0",
                GIT_SSH_COMMAND=f"{ssh} -o BatchMode=yes")


def run_git(root, *args):
    """stdout of ``git -C root args``; a failure raises Refused.

    git never reads the terminal, which the dashboard reads keys from,
    and never prompts for credentials.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            timeout=60, stdin=subprocess.DEVNULL, env=git_env())
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


def auto_targets(rows, targets, local_version, attempted, excluded=()):
    """(label, target) pairs auto mode should deploy to now.

    ``rows`` and ``targets`` are parallel and start with this machine,
    which is never a target; ``attempted`` holds labels already tried
    this run, ``excluded`` the labels deploy must skip.
    """
    picks = []
    for row, target in zip(rows[1:], targets[1:]):
        if (row.label in attempted or row.label in excluded
                or row.snapshot is None):
            continue
        entry = row.snapshot.plugin
        if deployable(plugin_state(local_version, entry), entry):
            picks.append((row.label, target))
    return picks


class Deployer:
    """Deploys in the background, at most one at a time per machine.

    The whole job runs off the caller's thread: finding the commit (which
    may fetch from GitHub) and then installing it.
    """

    def __init__(self, run=None, timeout=DEPLOY_TIMEOUT, git=run_git,
                 clock=time.monotonic):
        self.run = run or subprocess.run
        self.timeout = timeout
        self.git = git
        self.clock = clock
        self.lock = threading.Lock()
        # Auto mode starts several deploys at once; their commit lookups
        # (a fetch in one checkout) must not run side by side, or git
        # fails with "cannot lock ref".
        self.lookup = threading.Lock()
        self.status = {}
        self.finished = {}
        self.threads = {}

    def start(self, label, target, entry):
        """Begin deploying to ``target``; False if one is running.

        ``entry`` is this machine's own plugin entry, the source of the
        commit to install.
        """
        with self.lock:
            if self.status.get(label) == "deploying...":
                return False
            self.status[label] = "deploying..."
        thread = threading.Thread(
            target=self._deploy, args=(label, target, entry), daemon=True)
        self.threads[label] = thread
        thread.start()
        return True

    def _deploy(self, label, target, entry):
        try:
            with self.lookup:
                commit = source_commit(entry, self.git)
            done = self.run(install_argv(target, commit), capture_output=True,
                            text=True, timeout=self.timeout,
                            stdin=subprocess.DEVNULL)
            if done.returncode:
                lines = (done.stderr or done.stdout or "").strip().splitlines()
                result = "failed: " + (
                    lines[0] if lines else f"exit {done.returncode}")
            else:
                result = "deployed"
        except Refused as exc:
            result = f"refused: {exc}"
        except subprocess.TimeoutExpired:
            result = "failed: timeout"
        except Exception as exc:  # never leave a card deploying for good
            result = f"failed: {exc}"
        with self.lock:
            self.status[label] = result
            self.finished[label] = self.clock()

    def get(self, label, polled=None):
        """The latest result for ``label``, or None.

        ``polled`` is when the poll on screen began (``time.monotonic``).
        A "deployed" result gives way once a poll that began after the
        install ended is shown, because that poll reports the machine's
        real state. Failures and refusals stay until the next deploy.
        """
        with self.lock:
            status = self.status.get(label)
            if (status == "deployed" and polled is not None
                    and self.finished[label] < polled):
                return None
            return status
