"""statslib.herdr: the agent, workspace and tab reads the list needs."""

import json
import os
import subprocess

import pytest

from statslib import herdr

WORKSPACES = json.dumps({"id": "x", "result": {"workspaces": [
    {"workspace_id": "w1", "number": 5, "label": "api"},
    {"workspace_id": "w2", "number": 2},
    {"workspace_id": "w3", "label": "no number"},
    "not a workspace",
]}})
TABS = json.dumps({"result": {"tabs": [
    {"tab_id": "w1:t3", "workspace_id": "w1", "number": 18,
     "label": "review"},
    {"tab_id": "w1:t4", "workspace_id": "w1", "number": True},
]}})


def test_workspaces_by_id_with_number_and_label():
    assert herdr.workspaces(WORKSPACES) == {"w1": (5, "api"), "w2": (2, "")}


def test_tabs_by_id_skip_entries_without_a_real_number():
    assert herdr.tabs(TABS) == {"w1:t3": (18, "review")}


@pytest.mark.parametrize("text", [
    "", "garbage", "{}", '{"result": {}}', '{"result": {"tabs": 3}}'])
def test_unusable_lists_are_none(text):
    assert herdr.workspaces(text) is None
    assert herdr.tabs(text) is None
    assert herdr.agents(text) is None


def test_agents_are_the_dicts_of_the_agent_list():
    text = json.dumps({"result": {"agents": [
        {"pane_id": "w1:p2", "agent_status": "blocked"}, 7]}})
    assert herdr.agents(text) == [
        {"pane_id": "w1:p2", "agent_status": "blocked"}]


def test_screens_are_read_with_one_marker_line_per_pane(fake_herdr):
    shim, calls, canned = fake_herdr
    (canned / "agent-read").write_text("Do you want to proceed?\n❯ 1. Yes\n")
    env = dict(os.environ, PATH=f"{shim.parent}{os.pathsep}"
               f"{os.environ['PATH']}")
    out = subprocess.run(
        ["sh", "-c", herdr.read_shell(["w1:p1", "w1:p2"])], env=env,
        capture_output=True, text=True, timeout=20).stdout
    screen = ["Do you want to proceed?", "❯ 1. Yes"]
    assert herdr.screens(out) == {"w1:p1": screen, "w1:p2": screen}
    assert calls.read_text().splitlines() == [
        "agent read w1:p1 --source visible --format text",
        "agent read w1:p2 --source visible --format text"]


def test_focus_names_the_pane_here_and_in_a_remote_shell(fake_herdr,
                                                         monkeypatch):
    shim, calls, _canned = fake_herdr
    monkeypatch.setenv("HERDR_BIN", str(shim))
    herdr.focus("w1:p2")
    assert calls.read_text().splitlines() == ["agent focus w1:p2"]
    assert herdr.focus_shell("w1:p2") == "herdr agent focus w1:p2"
    assert herdr.focus_shell("a b") == "herdr agent focus 'a b'"


def test_a_pane_whose_read_fails_has_no_screen_entry(tmp_path):
    shim = tmp_path / "herdr"
    shim.write_text('#!/bin/sh\n[ "$3" = w1:p2 ] && exit 1\n'
                    'echo "screen of $3"\n')
    shim.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}{os.pathsep}"
               f"{os.environ['PATH']}")
    out = subprocess.run(
        ["sh", "-c", herdr.read_shell(["w1:p1", "w1:p2"])], env=env,
        capture_output=True, text=True, timeout=20).stdout
    assert herdr.screens(out) == {"w1:p1": ["screen of w1:p1"]}
