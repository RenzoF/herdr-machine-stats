"""statslib.config: the deploy setting."""

import pytest

from statslib import config


def test_a_missing_file_means_off(tmp_path):
    assert config.load(tmp_path) == ("off", None)


@pytest.mark.parametrize("mode", ["off", "ask", "auto"])
def test_each_mode_is_read(tmp_path, mode):
    (tmp_path / "config.toml").write_text(f'deploy = "{mode}"\n')
    assert config.load(tmp_path) == (mode, None)


def test_a_file_without_the_key_means_off(tmp_path):
    (tmp_path / "config.toml").write_text("# nothing yet\n")
    assert config.load(tmp_path) == ("off", None)


def test_an_unknown_mode_is_reported_and_off(tmp_path):
    (tmp_path / "config.toml").write_text('deploy = "always"\n')
    mode, note = config.load(tmp_path)
    assert mode == "off" and "'always'" in note and "off" in note


def test_broken_toml_is_reported_and_off(tmp_path):
    (tmp_path / "config.toml").write_text("deploy = \n")
    mode, note = config.load(tmp_path)
    assert mode == "off" and "config.toml" in note


def test_the_pipeline_url_defaults_to_none(tmp_path):
    assert config.load_pipeline_url(tmp_path) == ("", None)
    (tmp_path / "config.toml").write_text('deploy = "ask"\n')
    assert config.load_pipeline_url(tmp_path) == ("", None)


def test_the_pipeline_url_is_read(tmp_path):
    (tmp_path / "config.toml").write_text(
        'pipeline_url = "http://dispatcher.example:8787/status"\n')
    assert config.load_pipeline_url(tmp_path) == (
        "http://dispatcher.example:8787/status", None)


@pytest.mark.parametrize("value", ['"file:///etc/passwd"', '"nope"', "3"])
def test_a_pipeline_url_that_is_not_http_is_ignored_with_a_note(
        tmp_path, value):
    (tmp_path / "config.toml").write_text(f"pipeline_url = {value}\n")
    url, note = config.load_pipeline_url(tmp_path)
    assert url == "" and "pipeline_url" in note and "no pipeline" in note


def test_broken_toml_leaves_no_pipeline_card(tmp_path):
    (tmp_path / "config.toml").write_text("pipeline_url = \n")
    url, note = config.load_pipeline_url(tmp_path)
    assert url == "" and "config.toml" in note


def test_deploy_exclude_defaults_to_nobody(tmp_path):
    assert config.load_deploy_exclude(tmp_path) == ((), None)
    (tmp_path / "config.toml").write_text('deploy = "auto"\n')
    assert config.load_deploy_exclude(tmp_path) == ((), None)


def test_deploy_exclude_is_read_as_names(tmp_path):
    (tmp_path / "config.toml").write_text(
        'deploy_exclude = ["lab", "build box"]\n')
    assert config.load_deploy_exclude(tmp_path) == (
        ("lab", "build box"), None)


@pytest.mark.parametrize("value", ['"lab"', "[1]", '["lab", ""]', "true"])
def test_a_deploy_exclude_that_is_not_a_list_of_names_is_reported(
        tmp_path, value):
    (tmp_path / "config.toml").write_text(f"deploy_exclude = {value}\n")
    names, note = config.load_deploy_exclude(tmp_path)
    assert names == () and "deploy_exclude" in note and "off" in note
