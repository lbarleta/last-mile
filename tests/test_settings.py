"""
Configuration loading: defaults, then lastmile.toml.

Each test writes its own toml into tmp and calls ``load_settings`` on it, so
nothing depends on where pytest is run from.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from lastmile import settings
from lastmile.settings import Settings, load_settings

ONE = '[systems.sf]\nlake_path = "/srv/sf"\nfeeds_url = "https://sf/gbfs.json"\n'
TWO = (
    '[general]\ndefault_system = "austin"\n'
    '[systems.austin]\nlake_path = "lakes/austin"\n'
    'feeds_url = "https://austin/gbfs.json"\n'
    '[systems.sf]\nlake_path = "/srv/sf"\nfeeds_url = "https://sf/gbfs.json"\n'
    'feeds_lang = "es"\n'
)


def write_toml(tmp_path, body: str):
    path = tmp_path / "lastmile.toml"
    path.write_text(body, encoding="utf-8")
    return path


# --- layers -----------------------------------------------------------------


def test_defaults_apply_without_a_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv(settings.CONFIG_ENV)
    (tmp_path / "lastmile.toml").unlink()  # conftest's; cwd is tmp_path
    loaded = load_settings()
    assert loaded.coverage_radius_m == Settings().coverage_radius_m
    assert loaded.system == ""
    assert loaded.root == tmp_path.resolve()


def test_toml_overrides_defaults(tmp_path):
    path = write_toml(
        tmp_path,
        "[metrics]\ncoverage_radius_m = 450\n[general]\nrequest_timeout_s = 7\n",
    )
    loaded = load_settings(path)
    assert loaded.coverage_radius_m == 450
    assert loaded.request_timeout_s == 7
    assert loaded.root == tmp_path.resolve()


def test_only_the_config_path_is_read_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LASTMILE_COVERAGE_RADIUS_M", "600")
    path = write_toml(tmp_path, "[metrics]\ncoverage_radius_m = 450\n")
    assert load_settings(path).coverage_radius_m == 450


def test_values_take_the_type_of_their_default(tmp_path):
    path = write_toml(
        tmp_path,
        '[metrics]\nfleet_baseline_hours = [23, 0, 1]\nlow_station_bike_share = "0.25"\n'
        '[general]\nrequest_timeout_s = " 10 "\n',
    )
    loaded = load_settings(path)
    assert loaded.fleet_baseline_hours == (23, 0, 1)
    assert loaded.low_station_bike_share == 0.25
    assert loaded.request_timeout_s == 10


def test_relative_paths_resolve_against_the_config_directory(tmp_path):
    path = write_toml(
        tmp_path,
        '[systems.x]\nlake_path = "warehouse"\nfeeds_url = "u"\n'
        'boundary_geojson = "/abs/city.geojson"\n',
    )
    loaded = load_settings(path)
    assert loaded.lake_dir == tmp_path.resolve() / "warehouse"
    assert str(loaded.boundary_geojson_path) == "/abs/city.geojson"


def test_get_settings_is_cached_until_reloaded(tmp_path, monkeypatch):
    path = write_toml(tmp_path, "[metrics]\ncoverage_radius_m = 111\n")
    monkeypatch.setenv(settings.CONFIG_ENV, str(path))
    settings.get_settings.cache_clear()
    assert settings.get_settings().coverage_radius_m == 111
    write_toml(tmp_path, "[metrics]\ncoverage_radius_m = 222\n")
    assert settings.get_settings().coverage_radius_m == 111
    assert settings.reload_settings().coverage_radius_m == 222


# --- validation -------------------------------------------------------------


def test_an_unknown_key_is_rejected(tmp_path):
    path = write_toml(tmp_path, "[general]\ndatabase_url = 'postgres://x'\n")
    with pytest.raises(ValueError, match=r"\[general\].*database_url"):
        load_settings(path)


def test_a_bare_key_is_pointed_at_the_tables(tmp_path):
    path = write_toml(tmp_path, "coverage_radius_m = 450\n")
    with pytest.raises(ValueError, match=r"coverage_radius_m.*\[metrics\]"):
        load_settings(path)


def test_a_global_key_inside_a_system_is_rejected(tmp_path):
    path = write_toml(tmp_path, ONE + "coverage_radius_m = 400\n")
    with pytest.raises(ValueError, match=r"\[systems.sf\].*coverage_radius_m"):
        load_settings(path)


def test_every_field_has_exactly_one_home():
    homes = [key for keys in settings.TABLES.values() for key in keys]
    homes.remove("default_system")
    declared = [
        f.name for f in fields(Settings) if f.name not in settings.INTERNAL_FIELDS
    ]
    assert sorted(homes) == sorted(declared)


def test_a_bad_value_names_the_key(tmp_path):
    path = write_toml(tmp_path, '[metrics]\ncoverage_radius_m = "three hundred"\n')
    with pytest.raises(ValueError, match="coverage_radius_m"):
        load_settings(path)


def test_config_pointing_at_a_missing_file_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv(settings.CONFIG_ENV, str(tmp_path / "nowhere.toml"))
    with pytest.raises(FileNotFoundError, match="nowhere.toml"):
        load_settings()


# --- systems ----------------------------------------------------------------


def test_the_default_system_is_resolved_into_settings(tmp_path):
    loaded = load_settings(write_toml(tmp_path, TWO))
    assert loaded.system == "austin"
    assert loaded.systems == ("austin", "sf")
    assert loaded.feeds_url == "https://austin/gbfs.json"
    assert loaded.lake_dir == tmp_path.resolve() / "lakes" / "austin"


def test_another_system_can_be_asked_for(tmp_path):
    loaded = load_settings(write_toml(tmp_path, TWO), system="sf")
    assert loaded.system == "sf"
    assert loaded.feeds_url == "https://sf/gbfs.json"
    assert str(loaded.lake_dir) == "/srv/sf"


def test_select_system_applies_to_later_loads(tmp_path, monkeypatch):
    monkeypatch.setenv(settings.CONFIG_ENV, str(write_toml(tmp_path, TWO)))
    settings.select_system("sf")
    assert settings.get_settings().system == "sf"
    settings.select_system(None)
    assert settings.get_settings().system == "austin"


def test_a_system_falls_back_to_the_built_in_defaults(tmp_path):
    path = write_toml(tmp_path, TWO)
    assert load_settings(path).feeds_lang == Settings().feeds_lang
    assert load_settings(path, system="sf").feeds_lang == "es"


def test_an_unknown_system_names_the_configured_ones(tmp_path):
    with pytest.raises(ValueError, match="austin, sf"):
        load_settings(write_toml(tmp_path, TWO), system="nyc")


def test_selecting_a_system_without_any_configured_fails(tmp_path):
    with pytest.raises(ValueError, match="none"):
        load_settings(write_toml(tmp_path, ""), system="austin")


def test_a_missing_default_system_is_rejected(tmp_path):
    path = write_toml(tmp_path, TWO.replace('"austin"\n', '"nyc"\n', 1))
    with pytest.raises(ValueError, match="default_system 'nyc'"):
        load_settings(path)


def test_several_systems_need_a_default(tmp_path):
    path = write_toml(tmp_path, TWO.replace('default_system = "austin"\n', ""))
    with pytest.raises(ValueError, match="default_system"):
        load_settings(path)


def test_a_lone_system_needs_no_default(tmp_path):
    assert load_settings(write_toml(tmp_path, ONE)).system == "sf"


@pytest.mark.parametrize("key", settings.REQUIRED_SYSTEM_KEYS)
def test_a_system_must_name_its_lake_and_feed(tmp_path, key):
    body = "".join(line + "\n" for line in ONE.splitlines() if not line.startswith(key))
    with pytest.raises(ValueError, match=rf"\[systems.sf\].*{key}"):
        load_settings(write_toml(tmp_path, body))


def test_no_systems_means_no_lake(tmp_path):
    loaded = load_settings(write_toml(tmp_path, "[general]\nrequest_timeout_s = 5\n"))
    assert loaded.system == ""
    with pytest.raises(ValueError, match="systems"):
        _ = loaded.lake_dir


def test_a_system_without_a_boundary_says_so(tmp_path):
    with pytest.raises(ValueError, match="boundary_geojson.*'sf'"):
        _ = load_settings(write_toml(tmp_path, ONE)).boundary_geojson_path
