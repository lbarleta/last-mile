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


@pytest.fixture
def init_db(capsys, monkeypatch):
    """Run init-db against a lake, answering yes to its confirmation prompt."""

    def _run(lake: str) -> tuple[int, str, str]:
        monkeypatch.setattr("builtins.input", lambda prompt: "y")
        return run(capsys, "init-db", "--lake", lake)

    return _run


def test_collect_before_init_db_says_so(tmp_path, capsys):
    code, _, err = run(capsys, "collect", "--lake", str(tmp_path / "lake"))
    assert code == 1
    assert "init-db" in err


@pytest.mark.parametrize("feed_set", DOCKED)
def test_init_collect_status_round_trip(
    tmp_path, capsys, feed_transport, feed_set, init_db
):
    feed_transport(feed_set)
    lake = str(tmp_path / "lake")

    code, out, _ = init_db(lake)
    assert code == 0
    assert "station_information" in out

    code, out, _ = run(capsys, "collect", "--lake", lake)
    assert code == 0
    assert "snapshot" in out and "station_status" in out

    code, out, _ = run(capsys, "status", "--lake", lake)
    assert code == 0
    assert "Snapshots:" in out
    assert "station_status" in out
    assert "geofencing_zones" in out


def test_init_db_shows_the_lake_and_config_before_asking(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    lake = tmp_path / "lake"
    code, out, _ = run(capsys, "init-db", "--lake", str(lake))
    assert code == 1
    assert str(lake) in out
    assert "does not exist yet" in out
    assert "lastmile.toml" in out
    assert "gbfs.json" in out
    assert "Aborted" in out
    assert not lake.exists()


def test_init_db_without_a_terminal_does_not_proceed(tmp_path, capsys):
    lake = tmp_path / "lake"
    code, _, _ = run(capsys, "init-db", "--lake", str(lake))
    assert code == 1
    assert not lake.exists()


def test_init_db_proceeds_on_yes(tmp_path, capsys, feed_transport, monkeypatch):
    feed_transport("v30")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    code, out, _ = run(capsys, "init-db", "--lake", str(tmp_path / "lake"))
    assert code == 0
    assert "station_information" in out


def test_init_db_refuses_an_initialized_lake(
    tmp_path, capsys, feed_transport, init_db, monkeypatch
):
    feed_transport("v30")
    lake = str(tmp_path / "lake")
    init_db(lake)
    run(capsys, "collect", "--lake", lake, "--snapshot")

    def no_prompt(prompt):
        raise AssertionError("init-db prompted on an initialized lake")

    monkeypatch.setattr("builtins.input", no_prompt)
    code, _, err = run(capsys, "init-db", "--lake", lake)
    assert code == 1
    assert "already initialized" in err
    assert "last snapshot" in err
    assert "collect" in err


def test_init_db_reports_a_failed_path(
    tmp_path, capsys, feed_transport, monkeypatch, init_db
):
    feed_transport("v30")
    from lastmile.gbfs import GbfsClient

    def boom(self):
        raise RuntimeError("zones down")

    monkeypatch.setattr(GbfsClient, "geofencing_zones", boom)
    code, out, _ = init_db(str(tmp_path / "lake"))
    assert code == 1
    assert "station_information" in out
    assert "FAILED RuntimeError: zones down" in out


def test_init_db_archives_geofencing(tmp_path, capsys, feed_transport, init_db):
    feed_transport("freefloat_v30")
    lake = tmp_path / "lake"
    init_db(str(lake))
    assert len(geofencing.captures(lake)) == 1


def test_collect_can_refresh_reference_data(tmp_path, capsys, feed_transport, init_db):
    transport = feed_transport("v30")
    lake = str(tmp_path / "lake")
    init_db(lake)
    transport.requested.clear()

    code, _, _ = run(capsys, "collect", "--lake", lake, "--reference")
    assert code == 0
    assert "station_information" in transport.requested


def test_collect_can_archive_geofencing(tmp_path, capsys, feed_transport, init_db):
    transport = feed_transport("v30")
    lake = str(tmp_path / "lake")
    init_db(lake)
    transport.requested.clear()

    code, _, _ = run(capsys, "collect", "--lake", lake, "--geofencing")
    assert code == 0
    assert "geofencing_zones" in transport.requested


def test_collect_without_flags_runs_every_path(
    tmp_path, capsys, feed_transport, init_db
):
    transport = feed_transport("v30")
    lake = str(tmp_path / "lake")
    init_db(lake)
    transport.requested.clear()

    run(capsys, "collect", "--lake", lake)
    for feed in ("station_status", "station_information", "geofencing_zones"):
        assert feed in transport.requested


def test_a_selected_path_runs_alone(tmp_path, capsys, feed_transport, init_db):
    transport = feed_transport("v30")
    lake = str(tmp_path / "lake")
    init_db(lake)
    transport.requested.clear()

    run(capsys, "collect", "--lake", lake, "--reference")
    assert "station_status" not in transport.requested


def test_collect_report_is_one_line_per_path(tmp_path, capsys, feed_transport, init_db):
    feed_transport("v30")
    lake = str(tmp_path / "lake")
    init_db(lake)

    code, out, _ = run(capsys, "collect", "--lake", lake)
    assert code == 0
    header, *lines = out.strip().splitlines()
    assert header.endswith(f"collect {lake}")
    assert [line.split()[0] for line in lines] == [
        "snapshot",
        "reference",
        "geofencing",
    ]
    assert "station_status" in lines[0]
    assert lines[1].endswith("no changes")
    assert "unchanged:" in lines[2] and lines[2].endswith("1 capture(s)")


def test_collecting_a_stored_hour_says_so(tmp_path, capsys, feed_transport, init_db):
    feed_transport("v30")
    lake = str(tmp_path / "lake")
    init_db(lake)
    run(capsys, "collect", "--lake", lake, "--snapshot")

    _, out, _ = run(capsys, "collect", "--lake", lake, "--snapshot")
    assert out.strip().splitlines()[-1].endswith("no new rows")


def test_collect_names_the_reference_feeds_that_changed(
    tmp_path, capsys, feed_transport, monkeypatch, init_db
):
    feed_transport("v30")
    lake = str(tmp_path / "lake")
    init_db(lake)
    from lastmile.gbfs import GbfsClient

    original = GbfsClient.station_information

    def renamed(self):
        stations = original(self)
        return stations.assign(name=stations["name"].mask(stations.index == 0, "X"))

    monkeypatch.setattr(GbfsClient, "station_information", renamed)
    _, out, _ = run(capsys, "collect", "--lake", lake, "--reference")
    assert out.strip().splitlines()[-1].endswith("station_information 1 changed")


def test_a_failed_path_is_reported_and_the_rest_still_run(
    tmp_path, capsys, feed_transport, monkeypatch, init_db
):
    feed_transport("v30")
    lake = str(tmp_path / "lake")
    init_db(lake)
    from lastmile.gbfs import GbfsClient

    def boom(self):
        raise RuntimeError("feed down")

    monkeypatch.setattr(GbfsClient, "station_information", boom)
    code, out, _ = run(capsys, "collect", "--lake", lake)
    assert code == 1
    lines = out.strip().splitlines()
    assert any(
        line.startswith("  reference") and "FAILED RuntimeError: feed down" in line
        for line in lines
    )
    assert any(
        line.startswith("  snapshot") and "station_status" in line for line in lines
    )


def test_a_failed_discovery_is_reported_as_a_whole(
    tmp_path, capsys, feed_transport, monkeypatch, init_db
):
    feed_transport("v30")
    lake = str(tmp_path / "lake")
    init_db(lake)
    from lastmile import gbfs

    def boom(url, **kwargs):
        raise ConnectionError("no route")

    monkeypatch.setattr(gbfs.requests, "get", boom)
    code, out, _ = run(capsys, "collect", "--lake", lake)
    assert code == 1
    assert out.strip().splitlines()[-1].strip() == "FAILED ConnectionError: no route"


def test_status_of_an_empty_lake_points_at_init_db(tmp_path, capsys, init_db):
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
