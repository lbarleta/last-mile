"""
The ``lastmile`` command, driven through ``main`` against a tmp lake.

The lake is ``tmp_path / "lake"``, the one system conftest's config declares;
the ``--system`` tests write their own config with two.

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

    def _run() -> tuple[int, str, str]:
        monkeypatch.setattr("builtins.input", lambda prompt: "y")
        return run(capsys, "init-db")

    return _run


def test_collect_before_init_db_says_so(tmp_path, capsys):
    code, _, err = run(capsys, "collect")
    assert code == 1
    assert "init-db" in err


@pytest.mark.parametrize("feed_set", DOCKED)
def test_init_collect_status_round_trip(
    tmp_path, capsys, feed_transport, feed_set, init_db
):
    feed_transport(feed_set)

    code, out, _ = init_db()
    assert code == 0
    assert "station_information" in out

    code, out, _ = run(capsys, "collect")
    assert code == 0
    assert "snapshot" in out and "station_status" in out

    code, out, _ = run(capsys, "status")
    assert code == 0
    assert "Snapshots:" in out
    assert "station_status" in out
    assert "geofencing_zones" in out


def test_init_db_shows_the_lake_and_config_before_asking(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    lake = tmp_path / "lake"
    code, out, _ = run(capsys, "init-db")
    assert code == 1
    assert str(lake) in out
    assert "does not exist yet" in out
    assert "lastmile.toml" in out
    assert "gbfs.json" in out
    assert "Aborted" in out
    assert not lake.exists()


def test_init_db_without_a_terminal_does_not_proceed(tmp_path, capsys):
    lake = tmp_path / "lake"
    code, _, _ = run(capsys, "init-db")
    assert code == 1
    assert not lake.exists()


def test_init_db_proceeds_on_yes(tmp_path, capsys, feed_transport, monkeypatch):
    feed_transport("v30")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    code, out, _ = run(capsys, "init-db")
    assert code == 0
    assert "station_information" in out


def test_init_db_refuses_an_initialized_lake(
    tmp_path, capsys, feed_transport, init_db, monkeypatch
):
    feed_transport("v30")
    init_db()
    run(capsys, "collect", "--snapshot")

    def no_prompt(prompt):
        raise AssertionError("init-db prompted on an initialized lake")

    monkeypatch.setattr("builtins.input", no_prompt)
    code, _, err = run(capsys, "init-db")
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
    code, out, _ = init_db()
    assert code == 1
    assert "station_information" in out
    assert "FAILED RuntimeError: zones down" in out


def test_init_db_archives_geofencing(tmp_path, capsys, feed_transport, init_db):
    feed_transport("freefloat_v30")
    lake = tmp_path / "lake"
    init_db()
    assert len(geofencing.captures(lake)) == 1


def test_collect_can_refresh_reference_data(tmp_path, capsys, feed_transport, init_db):
    transport = feed_transport("v30")
    init_db()
    transport.requested.clear()

    code, _, _ = run(capsys, "collect", "--reference")
    assert code == 0
    assert "station_information" in transport.requested


def test_collect_can_archive_geofencing(tmp_path, capsys, feed_transport, init_db):
    transport = feed_transport("v30")
    init_db()
    transport.requested.clear()

    code, _, _ = run(capsys, "collect", "--geofencing")
    assert code == 0
    assert "geofencing_zones" in transport.requested


def test_collect_without_flags_runs_every_path(
    tmp_path, capsys, feed_transport, init_db
):
    transport = feed_transport("v30")
    init_db()
    transport.requested.clear()

    run(capsys, "collect")
    for feed in ("station_status", "station_information", "geofencing_zones"):
        assert feed in transport.requested


def test_a_selected_path_runs_alone(tmp_path, capsys, feed_transport, init_db):
    transport = feed_transport("v30")
    init_db()
    transport.requested.clear()

    run(capsys, "collect", "--reference")
    assert "station_status" not in transport.requested


def test_collect_report_is_one_line_per_path(tmp_path, capsys, feed_transport, init_db):
    feed_transport("v30")
    init_db()

    code, out, _ = run(capsys, "collect")
    assert code == 0
    header, *lines = out.strip().splitlines()
    assert header.endswith(f"collect test ({tmp_path / 'lake'})")
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
    init_db()
    run(capsys, "collect", "--snapshot")

    _, out, _ = run(capsys, "collect", "--snapshot")
    assert out.strip().splitlines()[-1].endswith("no new rows")


def test_collect_names_the_reference_feeds_that_changed(
    tmp_path, capsys, feed_transport, monkeypatch, init_db
):
    feed_transport("v30")
    init_db()
    from lastmile.gbfs import GbfsClient

    original = GbfsClient.station_information

    def renamed(self):
        stations = original(self)
        return stations.assign(name=stations["name"].mask(stations.index == 0, "X"))

    monkeypatch.setattr(GbfsClient, "station_information", renamed)
    _, out, _ = run(capsys, "collect", "--reference")
    assert out.strip().splitlines()[-1].endswith("station_information 1 changed")


def test_a_failed_path_is_reported_and_the_rest_still_run(
    tmp_path, capsys, feed_transport, monkeypatch, init_db
):
    feed_transport("v30")
    init_db()
    from lastmile.gbfs import GbfsClient

    def boom(self):
        raise RuntimeError("feed down")

    monkeypatch.setattr(GbfsClient, "station_information", boom)
    code, out, _ = run(capsys, "collect")
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
    init_db()
    from lastmile import gbfs

    def boom(url, **kwargs):
        raise ConnectionError("no route")

    monkeypatch.setattr(gbfs.requests, "get", boom)
    code, out, _ = run(capsys, "collect")
    assert code == 1
    assert out.strip().splitlines()[-1].strip() == "FAILED ConnectionError: no route"


# --- systems ---------------------------------------------------------------


@pytest.fixture
def two_systems(tmp_path):
    """A config naming two systems, each with its own lake under tmp."""
    toml = tmp_path / "systems.toml"
    toml.write_text(
        '[general]\ndefault_system = "austin"\n'
        '[systems.austin]\nlake_path = "data/lake/austin"\nfeeds_url = "gbfs.json"\n'
        '[systems.sf]\nlake_path = "data/lake/sf"\nfeeds_url = "gbfs.json"\n',
        encoding="utf-8",
    )
    return str(toml)


def test_system_flag_picks_that_systems_lake(
    tmp_path, capsys, feed_transport, two_systems, monkeypatch
):
    feed_transport("v30")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    code, out, _ = run(capsys, "init-db", "--system", "sf", "--config", two_systems)
    assert code == 0
    assert "System:  sf" in out
    assert (tmp_path / "data" / "lake" / "sf").is_dir()
    assert not (tmp_path / "data" / "lake" / "austin").exists()


def test_default_system_is_used_without_the_flag(
    tmp_path, capsys, feed_transport, two_systems, monkeypatch
):
    feed_transport("v30")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    _, out, _ = run(capsys, "init-db", "--config", two_systems)
    assert "System:  austin" in out
    assert (tmp_path / "data" / "lake" / "austin").is_dir()


def test_an_unknown_system_lists_the_configured_ones(capsys, two_systems):
    code, _, err = run(capsys, "status", "--system", "nyc", "--config", two_systems)
    assert code == 2
    assert "nyc" in err
    assert "austin, sf" in err


def test_collect_names_the_system_in_its_header(
    tmp_path, capsys, feed_transport, two_systems, monkeypatch
):
    feed_transport("v30")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    run(capsys, "init-db", "--system", "sf", "--config", two_systems)

    _, out, _ = run(capsys, "collect", "--system", "sf", "--config", two_systems)
    assert "collect sf (" in out.splitlines()[0]


def test_systems_are_collected_apart(
    tmp_path, capsys, feed_transport, two_systems, monkeypatch
):
    feed_transport("v30")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    run(capsys, "init-db", "--system", "austin", "--config", two_systems)

    code, _, err = run(capsys, "collect", "--system", "sf", "--config", two_systems)
    assert code == 1
    assert "init-db" in err


def test_status_of_an_empty_lake_points_at_init_db(tmp_path, capsys, init_db):
    code, out, _ = run(capsys, "status")
    assert code == 1
    assert "init-db" in out


def test_config_flag_reloads_settings(tmp_path, capsys):
    toml = tmp_path / "other.toml"
    toml.write_text(
        '[general]\nrequest_timeout_s = 7\n[systems.x]\nlake_path = "l"\nfeeds_url = "u"\n',
        encoding="utf-8",
    )
    run(capsys, "status", "--config", str(toml))
    assert settings.get_settings().request_timeout_s == 7


def test_a_config_without_systems_is_refused(tmp_path, capsys):
    toml = tmp_path / "bare.toml"
    toml.write_text("[general]\nrequest_timeout_s = 7\n", encoding="utf-8")
    code, _, err = run(capsys, "status", "--config", str(toml))
    assert code == 2
    assert "[systems.<name>]" in err


@pytest.mark.parametrize("command", ["weather", "forecast"])
def test_stub_commands_say_they_are_not_implemented(tmp_path, capsys, command):
    code, _, err = run(capsys, command)
    assert code == 1
    assert "not implemented" in err


def test_version_flag():
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
