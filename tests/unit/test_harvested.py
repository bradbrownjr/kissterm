"""The per-callsign cache behind opt-in command harvesting.

Same persistence contract as `tests/unit/test_addressbook.py`: a missing or
corrupt file degrades to empty rather than raising, and callsign matching is
case-insensitive.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import json  # noqa: E402

from kissterm.harvested import HarvestedCommands  # noqa: E402


def test_add_then_for_callsign_round_trips(tmp_path):
    cache = HarvestedCommands(tmp_path / "harvested.json")
    cache.add("WS1EC-15", ("CALENDAR", "FORMS", "WALL"))
    assert cache.for_callsign("WS1EC-15") == ("CALENDAR", "FORMS", "WALL")


def test_callsign_matching_is_case_insensitive(tmp_path):
    cache = HarvestedCommands(tmp_path / "harvested.json")
    cache.add("ws1ec-15", ("CALENDAR",))
    assert cache.for_callsign("WS1EC-15") == ("CALENDAR",)


def test_a_second_harvest_adds_rather_than_replaces(tmp_path):
    cache = HarvestedCommands(tmp_path / "harvested.json")
    cache.add("WS1EC-15", ("CALENDAR",))
    cache.add("WS1EC-15", ("FORMS", "CALENDAR"))
    assert cache.for_callsign("WS1EC-15") == ("CALENDAR", "FORMS")


def test_an_unknown_callsign_is_simply_empty(tmp_path):
    cache = HarvestedCommands(tmp_path / "harvested.json")
    assert cache.for_callsign("N0CALL") == ()


def test_a_missing_file_loads_as_empty(tmp_path):
    cache = HarvestedCommands(tmp_path / "does-not-exist.json")
    cache.load()
    assert cache.for_callsign("WS1EC-15") == ()


def test_a_corrupt_file_loads_as_empty_not_raising(tmp_path):
    file = tmp_path / "harvested.json"
    file.write_text("not json at all {{{", "utf-8")
    cache = HarvestedCommands(file)
    cache.load()
    assert cache.for_callsign("WS1EC-15") == ()


def test_persists_across_instances(tmp_path):
    file = tmp_path / "harvested.json"
    HarvestedCommands(file).add("WS1EC-15", ("CALENDAR", "FORMS"))
    reloaded = HarvestedCommands(file)
    reloaded.load()
    assert reloaded.for_callsign("WS1EC-15") == ("CALENDAR", "FORMS")


def test_written_as_valid_json(tmp_path):
    file = tmp_path / "harvested.json"
    HarvestedCommands(file).add("WS1EC-15", ("CALENDAR",))
    raw = json.loads(file.read_text("utf-8"))
    assert raw == {"WS1EC-15": [{"name": "CALENDAR", "context": "node"}]}


def test_loads_the_old_name_only_cache_as_node_commands(tmp_path):
    file = tmp_path / "harvested.json"
    file.write_text('{"WS1EC-15": ["CALENDAR"]}', "utf-8")
    cache = HarvestedCommands(file)
    cache.load()
    assert [(command.name, command.context) for command in cache.records_for_callsign("WS1EC-15")] == [
        ("CALENDAR", "node")
    ]


def test_keeps_bbs_commands_separate_from_node_commands(tmp_path):
    cache = HarvestedCommands(tmp_path / "harvested.json")
    cache.add("WS1EC-15", ("CONNECT",), context="node")
    cache.add("WS1EC-15", ("LIST", "SEND"), context="bbs")
    assert [(command.name, command.context) for command in cache.records_for_callsign("WS1EC-15")] == [
        ("CONNECT", "node"),
        ("LIST", "bbs"),
        ("SEND", "bbs"),
    ]
