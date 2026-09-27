"""Config tests.

The campus URL has three sources; which one wins decides which campus, and so which keyring
token, a command talks to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from moodle_cli.config import _config_dir, _settings_path, load_config, save_url, saved_url
from moodle_cli.errors import ConfigError
from tests.conftest import BASE_URL


def test_moodle_url_overrides_the_saved_url(monkeypatch: pytest.MonkeyPatch) -> None:
    save_url("https://saved.example.edu")
    monkeypatch.setenv("MOODLE_URL", BASE_URL)

    assert load_config().base_url == BASE_URL


def test_saved_url_is_used_when_moodle_url_is_unset(tmp_cwd: Path) -> None:
    """A directory with no .env anywhere above it still reaches the saved campus."""
    save_url(BASE_URL)

    assert load_config().base_url == BASE_URL


def test_explicit_base_url_overrides_every_other_source(monkeypatch: pytest.MonkeyPatch) -> None:
    save_url("https://saved.example.edu")
    monkeypatch.setenv("MOODLE_URL", "https://env.example.edu")

    assert load_config(base_url=f"{BASE_URL}/").base_url == BASE_URL


def test_no_url_from_any_source_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="No campus URL configured"):
        load_config()


def test_malformed_settings_file_counts_as_no_saved_url() -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")

    assert saved_url() is None


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("darwin", {}, Path("home", "Library", "Application Support", "moodle-cli")),
        ("win32", {"APPDATA": "appdata"}, Path("appdata", "moodle-cli")),
        ("win32", {}, Path("home", "AppData", "Roaming", "moodle-cli")),
        ("linux", {"XDG_CONFIG_HOME": "xdg"}, Path("xdg", "moodle-cli")),
        ("linux", {}, Path("home", ".config", "moodle-cli")),
    ],
)
def test_config_dir_follows_the_platform_convention(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform: str,
    env: dict[str, str],
    expected: Path,
) -> None:
    monkeypatch.setattr("sys.platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for name in ("APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, directory in env.items():
        monkeypatch.setenv(name, str(tmp_path / directory))

    # The imported name is the real function; the autouse isolation only replaces the
    # attribute on the config module.
    assert _config_dir() == tmp_path / expected
