"""statslib.herdr: the agent, workspace and tab reads the list needs."""

import json

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
