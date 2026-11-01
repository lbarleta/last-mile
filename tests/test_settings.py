"""
Configuration loading: defaults, then lastmile.toml, then the environment.

Each test writes its own toml into tmp and calls ``load_settings`` on it, so
nothing depends on where pytest is run from.
"""

from __future__ import annotations

import pytest

from lastmile import settings
from lastmile.settings import Settings, load_settings


def write_toml(tmp_path, body: str):
    path = tmp_path / "lastmile.toml"
    path.write_text(body, encoding="utf-8")
    return path


def env(name: str) -> str:
    return f"{settings.ENV_PREFIX}_{name}".upper()


def test_defaults_apply_without_a_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv(env("CONFIG"))
    monkeypatch.delenv(env("LAKE_PATH"))
    loaded = load_settings()
    defaults = Settings()
    assert loaded.lake_path == defaults.lake_path
    assert loaded.coverage_radius_m == defaults.coverage_radius_m
    assert loaded.root == tmp_path.resolve()


def test_toml_overrides_defaults(tmp_path):
    path = write_toml(tmp_path, 'coverage_radius_m = 450\nfeeds_lang = "fr"\n')
    loaded = load_settings(path)
    assert loaded.coverage_radius_m == 450
    assert loaded.feeds_lang == "fr"
    assert loaded.root == tmp_path.resolve()


def test_environment_overrides_toml(tmp_path, monkeypatch):
    path = write_toml(tmp_path, "coverage_radius_m = 450\n")
    monkeypatch.setenv(env("COVERAGE_RADIUS_M"), "600")
    assert load_settings(path).coverage_radius_m == 600


def test_dotenv_fills_in_but_never_overrides_the_environment(tmp_path, monkeypatch):
    path = write_toml(tmp_path, "")
    (tmp_path / ".env").write_text(
        f'{env("FEEDS_LANG")}="es"\n{env("COVERAGE_RADIUS_M")}=100\n# comment\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(env("COVERAGE_RADIUS_M"), "600")
    loaded = load_settings(path)
    assert loaded.feeds_lang == "es"
    assert loaded.coverage_radius_m == 600


def test_values_take_the_type_of_their_default(tmp_path, monkeypatch):
    path = write_toml(tmp_path, "fleet_baseline_hours = [23, 0, 1]\n")
    monkeypatch.setenv(env("LOW_STATION_BIKE_SHARE"), "0.25")
    monkeypatch.setenv(env("REQUEST_TIMEOUT_S"), " 10 ")
    loaded = load_settings(path)
    assert loaded.fleet_baseline_hours == (23, 0, 1)
    assert loaded.low_station_bike_share == 0.25
    assert loaded.request_timeout_s == 10


def test_a_list_in_the_environment_is_comma_separated(tmp_path, monkeypatch):
    path = write_toml(tmp_path, "")
    monkeypatch.setenv(env("FLEET_BASELINE_HOURS"), "22, 23,, 0")
    assert load_settings(path).fleet_baseline_hours == (22, 23, 0)


def test_relative_paths_resolve_against_the_config_directory(tmp_path, monkeypatch):
    monkeypatch.delenv(env("LAKE_PATH"))
    path = write_toml(
        tmp_path, 'lake_path = "warehouse"\nboundary_geojson = "/abs/city.geojson"\n'
    )
    loaded = load_settings(path)
    assert loaded.lake_dir == tmp_path.resolve() / "warehouse"
    assert str(loaded.boundary_geojson_path) == "/abs/city.geojson"


def test_an_unknown_key_is_rejected(tmp_path):
    path = write_toml(tmp_path, "database_url = 'postgres://x'\n")
    with pytest.raises(ValueError, match="database_url"):
        load_settings(path)


def test_a_bad_value_names_the_key(tmp_path, monkeypatch):
    path = write_toml(tmp_path, "")
    monkeypatch.setenv(env("COVERAGE_RADIUS_M"), "three hundred")
    with pytest.raises(ValueError, match="coverage_radius_m"):
        load_settings(path)


def test_config_pointing_at_a_missing_file_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv(env("CONFIG"), str(tmp_path / "nowhere.toml"))
    with pytest.raises(FileNotFoundError, match="nowhere.toml"):
        load_settings()


def test_unknown_environment_keys_warn_instead_of_vanishing(tmp_path, monkeypatch):
    path = write_toml(tmp_path, "")
    monkeypatch.setenv(env("DATABASE_URL"), "postgres://stale")
    with pytest.warns(UserWarning, match="LASTMILE_DATABASE_URL"):
        load_settings(path)


def test_get_settings_is_cached_until_reloaded(tmp_path, monkeypatch):
    path = write_toml(tmp_path, "coverage_radius_m = 111\n")
    monkeypatch.setenv(env("CONFIG"), str(path))
    assert settings.get_settings().coverage_radius_m == 111
    write_toml(tmp_path, "coverage_radius_m = 222\n")
    assert settings.get_settings().coverage_radius_m == 111
    assert settings.reload_settings().coverage_radius_m == 222
