"""build_topology: fungsi murni, tanpa DB (Phase 6)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.network.topology import (
    ISSUE_PIN_MISSING, ISSUE_PLAIN_API_PORT_WITH_TLS, ISSUE_PORT_NOT_ALLOWED,
    ISSUE_RELAY_NEEDS_API_SSL, AgentIn, DeviceIn, TargetIn, build_topology,
)

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def _agent(id="a1", status="online"):
    return AgentIn(id=id, name=f"agent-{id}", status=status, hostname="pc")


def _device(id="d1", port=8729, conn="api-ssl", reach="unknown", checked=None, name=None):
    return DeviceIn(id=id, name=name or f"dev-{id}", platform="mikrotik", host="192.168.7.5",
                    port=port, connection_type=conn, reachability=reach, last_checked_at=checked)


def _target(id="t1", agent="a1", device="d1", ports=(8729,), pinned=True):
    return TargetIn(id=id, agent_id=agent, device_id=device, host="192.168.7.5",
                    ports=tuple(ports), pinned=pinned)


def _node(topo, node_id):
    return next(n for n in topo["nodes"] if n["id"] == node_id)


def test_empty_has_only_nova():
    t = build_topology([], [], [], NOW)
    assert [n["id"] for n in t["nodes"]] == ["nova"]
    assert t["edges"] == []
    assert t["summary"]["devices_total"] == 0


def test_agent_to_device_edges_and_route():
    t = build_topology([_agent()], [_device()], [_target()], NOW)
    assert {(e["from"], e["to"], e["kind"]) for e in t["edges"]} == {
        ("nova", "agent:a1", "control"), ("agent:a1", "device:d1", "relay")}
    d = _node(t, "device:d1")
    assert d["route"] == "agent" and d["agent_id"] == "a1" and d["issues"] == []


def test_device_without_target_is_direct_and_unknown_never_online():
    d = _node(build_topology([_agent()], [_device(reach="online", checked=NOW)], [], NOW), "device:d1")
    assert d["route"] == "direct"
    assert d["status"] == "unknown"  # tidak ada probe langsung -> tidak boleh mengaku online


def test_agent_offline_overrides_even_fresh_online_probe():
    t = build_topology([_agent(status="disconnected")],
                       [_device(reach="online", checked=NOW)], [_target()], NOW)
    assert _node(t, "device:d1")["status"] == "agent_offline"
    assert t["summary"]["devices"]["agent_offline"] == 1


def test_fresh_probe_result_is_used():
    for reach in ("online", "offline"):
        t = build_topology([_agent()], [_device(reach=reach, checked=NOW - timedelta(seconds=30))],
                           [_target()], NOW)
        d = _node(t, "device:d1")
        assert d["status"] == reach and d["stale"] is False


def test_stale_probe_becomes_unknown_and_flagged():
    t = build_topology([_agent()], [_device(reach="online", checked=NOW - timedelta(hours=1))],
                       [_target()], NOW)
    d = _node(t, "device:d1")
    assert d["status"] == "unknown" and d["stale"] is True


def test_never_checked_is_unknown_not_stale():
    d = _node(build_topology([_agent()], [_device()], [_target()], NOW), "device:d1")
    assert d["status"] == "unknown" and d["stale"] is False and d["last_checked_at"] is None


def test_detects_the_real_world_misconfig_port_8728_with_api_ssl():
    d = _node(build_topology([], [_device(port=8728)], [], NOW), "device:d1")
    assert ISSUE_PLAIN_API_PORT_WITH_TLS in d["issues"]


def test_relay_issues_pin_port_and_connection_type():
    t = build_topology([_agent()], [_device(port=8728, conn="api")],
                       [_target(ports=(8729,), pinned=False)], NOW)
    issues = set(_node(t, "device:d1")["issues"])
    assert {ISSUE_PIN_MISSING, ISSUE_PORT_NOT_ALLOWED, ISSUE_RELAY_NEEDS_API_SSL} <= issues
    assert t["summary"]["devices_with_issues"] == 1


def test_picks_target_that_allows_the_port():
    t = build_topology([_agent("a1"), _agent("a2")], [_device(port=8729)],
                       [_target("t1", "a1", ports=(8728,)), _target("t2", "a2", ports=(8729,))], NOW)
    d = _node(t, "device:d1")
    assert d["agent_id"] == "a2" and d["issues"] == []
    assert [e["target_id"] for e in t["edges"] if e["kind"] == "relay"] == ["t2"]


def test_target_of_unknown_agent_or_without_device_is_ignored():
    t = build_topology([_agent("a1")], [_device()],
                       [_target("t1", agent="ghost"), _target("t2", device=None)], NOW)
    assert _node(t, "device:d1")["route"] == "direct"
    assert all(e["kind"] != "relay" for e in t["edges"])


def test_naive_datetimes_are_treated_as_utc():
    naive = datetime(2026, 11, 7, 11, 59, 30)  # tanpa tzinfo, 30 dtk lalu (UTC)
    t = build_topology([_agent()], [_device(reach="online", checked=naive)], [_target()], NOW)
    assert _node(t, "device:d1")["status"] == "online"


def test_summary_counts():
    t = build_topology(
        [_agent("a1"), _agent("a2", status="disconnected")],
        [_device("d1", reach="online", checked=NOW), _device("d2"), _device("d3")],
        [_target("t1", "a1", "d1"), _target("t2", "a2", "d2")], NOW)
    s = t["summary"]
    assert s["agents_total"] == 2 and s["agents_online"] == 1 and s["devices_total"] == 3
    assert s["devices"] == {"online": 1, "offline": 0, "agent_offline": 1, "unknown": 1}
