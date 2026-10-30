"""statslib.prompts: open secret requests, from their metadata only."""

import json
import os
import subprocess
import time

import pytest

from statslib import collect, needs, prompts

NAME = "secret-prompt"
RID = "r-0123abcd"


def make_request(base, rid=RID, **fields):
    """A request directory as a secret prompt writes it."""
    top = base / NAME
    top.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(top, 0o700)
    rdir = top / rid
    rdir.mkdir(mode=0o700)
    os.chmod(rdir, 0o700)
    now = time.time()
    request = {"id": rid, "path": "example/app", "key": "api_token",
               "purpose": "deploy the example app", "multiline": False,
               "host": "box", "pane_id": "w1:p2", "workspace_id": "w1",
               "created": now - 120, "expires": now + 600,
               "seen_version": 0}
    request.update(fields)
    (rdir / "request.json").write_text(json.dumps(request))
    return rdir


def scan(home, runtime=None):
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    if runtime is not None:
        env["XDG_RUNTIME_DIR"] = str(runtime)
    done = subprocess.run(["sh", "-c", prompts.scan_shell(NAME)],
                          env=env, capture_output=True, text=True,
                          timeout=20)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


def state_base(home):
    return home / ".local" / "state"


def found(home, runtime=None):
    return prompts.parse(scan(home, runtime), time.time())


def test_an_open_request_is_found_with_only_its_metadata(home):
    make_request(state_base(home))
    [req] = found(home)
    assert req.id == RID and req.pane_id == "w1:p2"
    assert req.workspace_id == "w1"
    assert req.purpose == "deploy the example app"
    assert req.prompt_pane is None
    assert "example/app" not in repr(req) and "api_token" not in repr(req)


def test_the_prompt_pane_comes_from_pane_json(home):
    rdir = make_request(state_base(home))
    (rdir / "pane.json").write_text('{"pane_id": "w1:p9"}')
    assert found(home)[0].prompt_pane == "w1:p9"


@pytest.mark.parametrize("name", ["result.json", "cancel.json"])
def test_an_answered_or_cancelled_request_is_not_open(home, name):
    rdir = make_request(state_base(home))
    (rdir / name).write_text('{"status": "stored"}')
    assert found(home) == []


def test_the_scan_never_prints_a_result_file(home):
    rdir = make_request(state_base(home))
    (rdir / "result.json").write_text("NOT-FOR-THE-DASHBOARD")
    (rdir / "other.txt").write_text("NOT-FOR-THE-DASHBOARD")
    assert "NOT-FOR-THE-DASHBOARD" not in scan(home)


def test_an_expired_request_is_not_open(home):
    make_request(state_base(home), expires=time.time() - 1)
    assert found(home) == []


@pytest.mark.parametrize("phase, age, listed", [
    ("typing", 10, True),     # fresh: its deadline counts
    ("typing", 100, False),   # older than 90 s: expires counts
    ("writing", 150, True),   # writing stays fresh for 210 s
    ("writing", 220, False),
])
def test_a_fresh_state_file_moves_the_deadline(home, phase, age, listed):
    now = time.time()
    rdir = make_request(state_base(home), expires=now - 1)
    (rdir / "state.json").write_text(json.dumps(
        {"phase": phase, "deadline": now + 300, "at": now - age}))
    reqs = found(home)
    assert bool(reqs) is listed
    if listed:
        assert abs(reqs[0].deadline - (now + 300)) < 1


def test_runtime_and_state_directories_are_both_scanned_once_each(
        home, tmp_path):
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    make_request(runtime, rid="r-11111111")
    make_request(state_base(home), rid="r-22222222")
    make_request(state_base(home), rid="r-11111111")  # the same request
    assert sorted(r.id for r in found(home, runtime)) == [
        "r-11111111", "r-22222222"]


def test_a_symlinked_request_directory_is_skipped(home, tmp_path):
    real = make_request(tmp_path / "elsewhere")
    base = state_base(home) / NAME
    base.mkdir(parents=True, mode=0o700)
    (base / RID).symlink_to(real)
    assert found(home) == []


def test_a_directory_others_can_read_is_skipped(home):
    rdir = make_request(state_base(home))
    os.chmod(rdir, 0o750)
    assert found(home) == []


@pytest.mark.parametrize("rid", ["r-xyz", "r-0123abcd0", "x-0123abcd"])
def test_a_directory_not_named_like_a_request_is_skipped(home, rid):
    make_request(state_base(home), rid=rid, id=rid)
    assert found(home) == []


def test_a_request_older_than_a_day_is_skipped(home):
    rdir = make_request(state_base(home))
    old = time.time() - 25 * 3600
    os.utime(rdir, (old, old))
    assert found(home) == []


@pytest.mark.parametrize("fields", [
    {"created": "soon"}, {"expires": True}, {"pane_id": 7},
    {"id": "r-ffffffff"}, {"purpose": "x" * 5000},
])
def test_a_malformed_or_oversized_request_is_skipped(home, fields):
    make_request(state_base(home), **fields)
    assert found(home) == []


def test_text_that_is_not_json_is_skipped(home):
    rdir = make_request(state_base(home))
    (rdir / "request.json").write_text("not json")
    assert found(home) == []


def test_the_collector_reports_requests_only_when_asked(
        fake_herdr, home, monkeypatch):
    shim, _calls, _canned = fake_herdr
    make_request(state_base(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    env = dict(os.environ, PATH=f"{shim.parent}{os.pathsep}"
               f"{os.environ['PATH']}")

    def raw(request_dir):
        out = subprocess.run(
            ["sh", "-c", collect.script(False, request_dir)], env=env,
            capture_output=True, text=True, timeout=30).stdout
        return needs.parse_raw(collect.sections(out))

    assert [r.id for r in raw(NAME).requests] == [RID]
    assert raw("").requests == []
    assert collect.REQUESTS_MARKER not in collect.script(False, "")
