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
