"""statslib.deploy: plugin state, the commit to deploy, installs."""

import subprocess
import threading

import pytest

from statslib import collect, deploy


def entry(version="0.2.0", kind="github", commit="c0ffee", root="/opt/p"):
    source = {"kind": kind}
    if kind == "github":
        source["resolved_commit"] = commit
    return {"version": version, "plugin_root": root, "source": source}


@pytest.mark.parametrize("text, want", [
    ("0.2.0", (0, 2, 0)), ("1.10", (1, 10)), ("", None), ("1.x", None),
])
def test_version_key_compares_dotted_integers(text, want):
    assert deploy.version_key(text) == want


@pytest.mark.parametrize("remote, want", [
    (entry("0.2.0"), "current"),
    (entry("0.1.9"), "older"),
    (entry("0.10.0"), "newer"),  # 10 > 2 as integers, not as text
    ({}, "missing"),
    (None, "unknown"),
    (entry("weird"), "unknown"),
])
def test_plugin_state_compares_against_this_copy(remote, want):
    assert deploy.plugin_state("0.2.0", remote) == want


@pytest.mark.parametrize("state, remote, want", [
    ("missing", {}, True),
    ("older", entry("0.1.0"), True),
    ("older", entry("0.1.0", kind="local"), False),  # someone's checkout
    ("newer", entry("0.3.0"), False),
    ("current", entry(), False),
    ("unknown", None, False),
])
def test_only_missing_or_older_github_installs_are_deployable(
        state, remote, want):
    assert deploy.deployable(state, remote) is want


def test_source_commit_of_a_github_install_is_its_resolved_commit():
    assert deploy.source_commit(entry(commit="abc123")) == "abc123"


def fake_git(answers):
    calls = []

    def git(root, *args):
        calls.append(args)
        answer = answers.get(args[0], "")
        if isinstance(answer, Exception):
            raise answer
        return answer
    return git, calls


def test_source_commit_of_a_linked_copy_is_its_published_head():
    git, calls = fake_git({"status": "", "rev-parse": "abc123",
                           "fetch": "", "branch": "  origin/main"})
    assert deploy.source_commit(entry(kind="local"), git) == "abc123"
    assert calls == [("status", "--porcelain"), ("rev-parse", "HEAD"),
                     ("fetch", "--quiet", "origin"),
                     ("branch", "-r", "--contains", "abc123")]


@pytest.mark.parametrize("answers, reason", [
    ({"status": " M bin/x"}, "uncommitted changes"),
    ({"status": "", "rev-parse": "abc123", "fetch": "", "branch": ""},
     "abc123 is not on GitHub"),
])
def test_source_commit_refuses_unpublished_code(answers, reason):
    git, _calls = fake_git(answers)
    with pytest.raises(deploy.Refused, match=reason):
        deploy.source_commit(entry(kind="local"), git)


@pytest.mark.parametrize("local", [None, {}])
def test_source_commit_refuses_without_an_installed_copy_here(local):
    with pytest.raises(deploy.Refused, match="no installed copy"):
        deploy.source_commit(local)


def test_run_git_turns_a_failure_into_refused(tmp_path):
    with pytest.raises(deploy.Refused):
        deploy.run_git(tmp_path, "rev-parse", "HEAD")  # not a repository


def test_install_argv_installs_the_pinned_commit_over_ssh():
    argv = deploy.install_argv("me@10.0.0.9", "abc123")
    assert argv[:5] == ["ssh", "-o", "BatchMode=yes", "-o",
                        "ConnectTimeout=5"]
    assert argv[5] == "me@10.0.0.9"
    assert ("herdr plugin install RenzoF/herdr-machine-stats --ref abc123"
            " --yes") in argv[6]


def row(label, remote):
    snap = collect.Snapshot(
        os="Linux", ncpu=1, load=0.0, cpu_pct=0, mem_pct=0, mem_used_kb=0,
        mem_total_kb=1, disk_pct=0, disk_used_kb=0, disk_total_kb=1,
        agents={}, plugin=remote)
    return collect.Row(label, snap, None)


def test_auto_targets_skips_this_machine_and_machines_already_tried():
    rows = [row("here", {}), row("a", {}), row("b", entry("0.1.0")),
            row("c", entry()), collect.Row("d", None, "timeout"),
            row("e", {})]
    targets = [None, "ta", "tb", "tc", "td", "te"]
    assert deploy.auto_targets(rows, targets, "0.2.0", {"e"}) == [
        ("a", "ta"), ("b", "tb")]


def done(code=0, err=""):
    return subprocess.CompletedProcess([], code, "", err)


def test_deployer_reports_success_and_the_first_error_line():
    ok = deploy.Deployer(run=lambda *a, **k: done())
    ok.start("a", "ta", "abc")
    ok.threads["a"].join(5)
    assert ok.get("a") == "deployed"
    bad = deploy.Deployer(run=lambda *a, **k: done(1, "no access\nmore"))
    bad.start("a", "ta", "abc")
    bad.threads["a"].join(5)
    assert bad.get("a") == "failed: no access"


def test_deployer_runs_one_install_per_machine_at_a_time():
    release = threading.Event()
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        release.wait(5)
        return done()
    deployer = deploy.Deployer(run=run)
    assert deployer.start("a", "ta", "abc") is True
    assert deployer.get("a") == "deploying..."
    assert deployer.start("a", "ta", "abc") is False
    release.set()
    deployer.threads["a"].join(5)
    assert len(seen) == 1 and seen[0] == deploy.install_argv("ta", "abc")


def test_deployer_reports_a_timeout():
    def run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
    deployer = deploy.Deployer(run=run, timeout=7)
    deployer.start("a", "ta", "abc")
    deployer.threads["a"].join(5)
    assert deployer.get("a") == "failed: timeout"
