"""The sweep must cover the subnet, and say so when it does not.

The bug this pins down: a /24 across seven ports is ~1500 connection
attempts, and the sweep ran 64 at a time with a 0.75 s per-attempt timeout
inside a 3 s overall budget -- about 21 seconds of work in a 3 second window.
It gave up after 43 of 254 addresses and returned its partial results with no
indication they were partial, so a TNC at .128 was invisible while a web
server at .3 was offered as a transport.

Two things had to change and both are asserted here: the sweep reaches every
address, and the ordering degrades sensibly if it ever cannot.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

import kissterm.discovery as discovery  # noqa: E402
from kissterm.discovery import ScanCoverage  # noqa: E402


@pytest.fixture
def attempts(monkeypatch):
    """Record every (host, port) the sweep tries, without touching a network."""
    seen: list[tuple[str, int]] = []

    async def fake_open_connection(host, port, *args, **kwargs):
        seen.append((host, port))
        raise OSError("nothing here")

    monkeypatch.setattr(discovery.asyncio, "open_connection", fake_open_connection)
    return seen


@pytest.mark.asyncio
async def test_the_whole_subnet_is_reached(attempts):
    coverage = ScanCoverage()
    await discovery.discover_network(subnet="10.6.26", timeout=10.0, coverage=coverage)

    octets = {int(host.split(".")[-1]) for host, _port in attempts}
    assert octets == set(range(1, 255)), (
        f"missed {sorted(set(range(1, 255)) - octets)[:10]}..."
    )
    assert coverage.hosts_reached == 254
    assert not coverage.truncated
    assert "scanned all 254" in coverage.summary


@pytest.mark.asyncio
async def test_the_radio_room_address_is_not_special(attempts):
    """.128 is the real one that was being missed. Sits past the point the
    old sweep gave up, which is the only reason it deserves its own test."""
    await discovery.discover_network(subnet="10.6.26", timeout=10.0)
    probed = {port for host, port in attempts if host == "10.6.26.128"}
    assert 8000 in probed and 8001 in probed, probed


@pytest.mark.asyncio
async def test_ports_are_the_outer_loop_so_truncation_loses_ports_not_hosts(attempts):
    """Every host gets probed on the most likely port before any host gets
    probed on the least likely one. A sweep that runs short then degrades to
    "all hosts, fewer ports" rather than "a few hosts, every port" -- the
    latter is what hid a TNC at .128 behind a web server at .3."""
    await discovery.discover_network(subnet="10.6.26", timeout=10.0)

    first_port = attempts[0][1]
    # The entire first block of attempts must be one port across many hosts.
    first_block = attempts[:254]
    assert {port for _host, port in first_block} == {first_port}
    assert len({host for host, _port in first_block}) == 254


@pytest.mark.asyncio
async def test_a_truncated_sweep_says_so_instead_of_looking_complete(monkeypatch):
    """The actual defect. A scan that gives up early and reports normally
    sends an operator to check cabling that is fine."""

    async def slow_open_connection(host, port, *args, **kwargs):
        await asyncio.sleep(5.0)
        raise OSError("nothing here")

    monkeypatch.setattr(discovery.asyncio, "open_connection", slow_open_connection)

    coverage = ScanCoverage()
    await discovery.discover_network(subnet="10.6.26", timeout=0.5, coverage=coverage)

    assert coverage.truncated, "a sweep that skipped most of its work looked complete"
    assert coverage.probes_done < coverage.probes_planned
    assert "ran out of time" in coverage.summary
    assert "add it by hand" in coverage.summary

    # And the degradation is the designed one: ports are the outer loop, so
    # even this badly truncated sweep still touched every ADDRESS on the
    # likeliest port. That is precisely why truncation has to be counted in
    # probes -- counting hosts would call this sweep complete.
    assert coverage.hosts_reached == coverage.hosts_planned


@pytest.mark.asyncio
async def test_vara_data_ports_are_not_swept(attempts):
    """8301/8401 are the data half of a two-port modem, never a device of
    their own -- probing them is 508 pointless connections."""
    await discovery.discover_network(subnet="10.6.26", timeout=10.0)
    probed_ports = {port for _host, port in attempts}
    assert 8301 not in probed_ports
    assert 8401 not in probed_ports
    assert 8300 in probed_ports, "the VARA command port is still worth finding"


@pytest.mark.asyncio
async def test_no_subnet_is_not_a_crash(monkeypatch):
    monkeypatch.setattr(discovery, "_guess_local_subnet", lambda: None)
    coverage = ScanCoverage()
    assert await discovery.discover_network(coverage=coverage) == []
    assert coverage.summary == "no subnet to scan"
