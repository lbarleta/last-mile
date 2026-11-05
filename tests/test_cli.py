"""
The ``lastmile`` command, driven through ``main`` against a tmp lake.

Feeds come from the recorded fixtures; the client resolves them by name, so
the configured Austin URL works unchanged.
"""

from __future__ import annotations

import pytest

from lastmile import cli, geofencing, settings

DOCKED = ("v23", "v30")


def run(capsys, *args: str) -> tuple[int, str, str]:
    code = cli.main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_collect_before_init_db_says_so(tmp_path, capsys):
    code, _, err = run(capsys, "collect", "--lake", str(tmp_path / "lake"))
    assert code == 1
    assert "init-db" in err


@pytest.mark.parametrize("feed_set", DOCKED)
def test_init_collect_status_round_trip(tmp_path, capsys, feed_transport, feed_set):
    feed_transport(feed_set)
    lake = str(tmp_path / "lake")

    code, out, _ = run(capsys, "init-db", "--lake", lake)
    assert code == 0
    assert "station_information" in out

    code, out, _ = run(capsys, "collect", "--lake", lake)
    assert code == 0
    assert "rows written" in out

    code, out, _ = run(capsys, "status", "--lake", lake)
    assert code == 0
    assert "Snapshots:" in out
    assert "station_status" in out
    assert "geofencing_zones" in out


def test_init_db_archives_geofencing(tmp_path, capsys, feed_transport):
    feed_transport("freefloat_v30")
    lake = tmp_path / "lake"
    run(capsys, "init-db", "--lake", str(lake))
    assert len(geofencing.captures(lake)) == 1


def test_collect_can_refresh_reference_data(tmp_path, capsys, feed_transport):
    transport = feed_transport("v30")
    lake = str(tmp_path / "lake")
    run(capsys, "init-db", "--lake", lake)
    transport.requested.clear()

    code, _, _ = run(capsys, "collect", "--lake", lake, "--reference")
    assert code == 0
    assert "station_information" in transport.requested


def test_collect_can_archive_geofencing(tmp_path, capsys, feed_transport):
    transport = feed_transport("v30")
    lake = str(tmp_path / "lake")
    run(capsys, "init-db", "--lake", lake)
    transport.requested.clear()

    code, _, _ = run(capsys, "collect", "--lake", lake, "--geofencing")
    assert code == 0
    assert "geofencing_zones" in transport.requested


def test_collect_without_flags_runs_every_path(tmp_path, capsys, feed_transport):
    transport = feed_transport("v30")
    lake = str(tmp_path / "lake")
    run(capsys, "init-db", "--lake", lake)
    transport.requested.clear()

    run(capsys, "collect", "--lake", lake)
    for feed in ("station_status", "station_information", "geofencing_zones"):
        assert feed in transport.requested


def test_a_selected_path_runs_alone(tmp_path, capsys, feed_transport):
    transport = feed_transport("v30")
    lake = str(tmp_path / "lake")
    run(capsys, "init-db", "--lake", lake)
    transport.requested.clear()

    run(capsys, "collect", "--lake", lake, "--reference")
    assert "station_status" not in transport.requested


def test_status_of_an_empty_lake_points_at_init_db(tmp_path, capsys):
    code, out, _ = run(capsys, "status", "--lake", str(tmp_path / "lake"))
    assert code == 1
    assert "init-db" in out


def test_config_flag_reloads_settings(tmp_path, capsys):
    toml = tmp_path / "other.toml"
    toml.write_text('feeds_lang = "fr"\n', encoding="utf-8")
    run(capsys, "status", "--lake", str(tmp_path / "lake"), "--config", str(toml))
    assert settings.get_settings().feeds_lang == "fr"


@pytest.mark.parametrize("command", ["weather", "forecast"])
def test_stub_commands_say_they_are_not_implemented(tmp_path, capsys, command):
    code, _, err = run(capsys, command, "--lake", str(tmp_path / "lake"))
    assert code == 1
    assert "not implemented" in err


def test_version_flag():
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
