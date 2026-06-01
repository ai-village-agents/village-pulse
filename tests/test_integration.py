"""End-to-end integration tests for the full Village Pulse pipeline.

These exercise the real ``api_client -> analytics -> report`` chain without
touching the network:

* :func:`test_client_pipeline_with_mock_session` drives a real
  :class:`~village_pulse.api_client.VillageAPIClient` with a fake HTTP session,
  so the actual event-flattening, metric computation, and HTML rendering all
  run together.
* :func:`test_cli_end_to_end_mocked` runs the CLI ``main()`` with
  ``api_client.fetch_events`` monkeypatched, verifying the __main__ wiring
  (fetch -> compute_all -> generate) and the on-disk HTML artifact.
"""

from __future__ import annotations

import json


from village_pulse import analytics
from village_pulse.api_client import VillageAPIClient
from village_pulse.report import generate


# ---------------------------------------------------------------------------
# Fake HTTP layer
# ---------------------------------------------------------------------------

VILLAGE_ID = "vid-123"

VILLAGE_DETAIL = {
    "id": VILLAGE_ID,
    "slug": "actual-launch-1",
    "createdAt": "2025-04-02T00:00:00Z",
    "agents": [
        {"id": "a1", "name": "GPT-5.5"},
        {"id": "a2", "name": "Kimi K2.6"},
        {"id": "a3", "name": "Claude Opus 4.8"},
    ],
    "chatRooms": [
        {"id": "r-best", "name": "best"},
        {"id": "r-rest", "name": "rest"},
    ],
}

EVENTS_PAGE = {
    "events": [
        {
            "id": "e1",
            "eventIndex": 10,
            "createdAt": "2026-06-01T17:00:00Z",
            "data": {
                "actionType": "AGENT_TALK",
                "speakerId": "a1",
                "roomId": "r-best",
                "content": "report module is ready",
            },
        },
        {
            "id": "e2",
            "eventIndex": 11,
            "createdAt": "2026-06-01T17:05:00Z",
            "data": {
                "actionType": "AGENT_TALK",
                "speakerId": "a2",
                "roomId": "r-best",
                "content": "cli wired up",
            },
        },
        {
            "id": "e3",
            "eventIndex": 12,
            "createdAt": "2026-06-01T17:10:00Z",
            "data": {
                "actionType": "AGENT_TALK",
                "speakerId": "a3",
                "roomId": "r-best",
                "content": "analytics locked",
            },
        },
        {
            "id": "e4",
            "eventIndex": 13,
            "createdAt": "2026-06-01T17:12:00Z",
            "data": {
                "actionType": "CONSOLIDATE",
                "speakerId": "a3",
                "roomId": "r-best",
                "nextSessionGoal": "keep following the leader",
            },
        },
    ],
    "hasMore": False,
}


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeSession:
    """Routes the handful of URLs the client hits to canned JSON."""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, url, timeout=None, headers=None):  # noqa: D401 - matches requests
        self.calls.append(url)
        if "/events" in url:
            return _FakeResponse(EVENTS_PAGE)
        if f"villages/{VILLAGE_ID}" in url:
            return _FakeResponse(VILLAGE_DETAIL)
        if "villages" in url:
            return _FakeResponse({"id": VILLAGE_ID, "slug": "actual-launch-1"})
        return _FakeResponse({"error": "not found"}, status=404)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_client_pipeline_with_mock_session(tmp_path):
    """Real client + fake transport feeds analytics + report end-to-end."""
    session = _FakeSession()
    client = VillageAPIClient(village_id=VILLAGE_ID, session=session)

    events = client.fetch_events(days=1, current_day=426)

    # api_client flattened + resolved names/rooms correctly.
    assert len(events) == 4
    assert {e["agent_name"] for e in events} == {"GPT-5.5", "Kimi K2.6", "Claude Opus 4.8"}
    assert all(e["room"] == "best" for e in events)
    # Oldest-first ordering by event_index.
    assert [e["event_index"] for e in events] == [10, 11, 12, 13]

    metrics = analytics.compute_all(events)
    assert metrics["meta"]["total_events"] == 4
    assert metrics["meta"]["total_messages"] == 3  # CONSOLIDATE is not a message
    assert metrics["messages_per_agent"]["GPT-5.5"] == 1
    assert metrics["action_type_breakdown"]["CONSOLIDATE"] == 1

    output = tmp_path / "dashboard.html"
    resolved = generate(metrics, output, {"room": "#best", "days": 1, "version": "0.1.0"})
    html = resolved.read_text(encoding="utf-8")
    assert "Village Pulse Dashboard" in html
    for name in ("GPT-5.5", "Kimi K2.6", "Claude Opus 4.8"):
        assert name in html


def test_cli_end_to_end_mocked(tmp_path, monkeypatch, capsys):
    """CLI main() wires fetch -> compute_all -> generate and writes HTML."""
    captured_kwargs = {}

    def fake_fetch(**kwargs):
        captured_kwargs.update(kwargs)
        # Return flat events as api_client.fetch_events would.
        return [
            {
                "agent_name": "GPT-5.5",
                "room": "best",
                "created_at": "2026-06-01T17:00:00Z",
                "action_type": "AGENT_TALK",
                "content": "hello",
            },
            {
                "agent_name": "Kimi K2.6",
                "room": "best",
                "created_at": "2026-06-01T17:05:00Z",
                "action_type": "AGENT_TALK",
                "content": "world",
            },
        ]

    import village_pulse.api_client as ac  # fresh module (test_cli may have reset sys.modules)
    monkeypatch.setattr(ac, "fetch_events", fake_fetch)

    from village_pulse.__main__ import main

    out = tmp_path / "report.html"
    rc = main(["--days", "2", "--room", "#best", "--output", str(out)])

    assert rc == 0
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "Village Pulse Dashboard" in html
    assert "GPT-5.5" in html and "Kimi K2.6" in html
    # CLI forwarded its args into fetch_events.
    assert captured_kwargs.get("days") == 2
    assert captured_kwargs.get("room") == "#best"


def test_cli_handles_api_error(tmp_path, monkeypatch):
    """An APIError from fetch surfaces as exit code 2, not a crash."""
    import village_pulse.api_client as ac  # fresh module (test_cli may have reset sys.modules)

    def boom(**kwargs):
        raise ac.APIError("simulated outage", status=503)

    monkeypatch.setattr(ac, "fetch_events", boom)
    from village_pulse.__main__ import main

    rc = main(["--output", str(tmp_path / "x.html")])
    assert rc == 2


# ---------------------------------------------------------------------------
# Multi-day trend-series contract (consumed by archive_compare)
# ---------------------------------------------------------------------------

def _talk(agent, room, ts, *, inp=0, out=0):
    return {
        "agentName": agent,
        "room": room,
        "createdAt": ts,
        "actionType": "AGENT_TALK",
        "content": "x",
        "inputTokens": inp,
        "outputTokens": out,
    }


def test_multi_day_trend_series_contract():
    """Guards the daily_trends / top_agents_over_time / room_daily_trends shapes
    documented in docs/analytics_contract.md and consumed by archive_compare."""
    events = [
        _talk("Alice", "best", "2026-05-30T10:00:00Z", inp=100, out=10),
        _talk("Bob", "best", "2026-05-30T11:00:00Z", inp=50, out=5),
        _talk("Alice", "best", "2026-05-31T09:00:00Z", inp=200, out=20),
        # Gap on 2026-06-01 in #best; activity only in #rest that day.
        _talk("Alice", "rest", "2026-06-02T09:00:00Z", inp=300, out=30),
    ]
    ca = analytics.compute_all(events)

    # daily_trends: oldest-first, one entry per active UTC day, sparse (gaps omitted).
    dt = ca["daily_trends"]
    assert [d["date"] for d in dt] == ["2026-05-30", "2026-05-31", "2026-06-02"]
    assert dt[0] == {
        "date": "2026-05-30", "events": 2, "messages": 2, "active_agents": 2,
        "input_tokens": 150, "output_tokens": 15, "total_tokens": 165,
        "efficiency": 10.0,
    }

    # top_agents_over_time: ranked desc, each with oldest-first sparse daily series.
    tops = ca["top_agents_over_time"]
    assert tops[0]["agent"] == "Alice"
    assert tops[0]["total_messages"] == 3
    assert [d["date"] for d in tops[0]["daily"]] == [
        "2026-05-30", "2026-05-31", "2026-06-02",
    ]

    # room_daily_trends: keyed by room NAME (sorted), each value mirrors daily_trends.
    rdt = ca["room_daily_trends"]
    assert sorted(rdt) == ["best", "rest"]
    assert [d["date"] for d in rdt["best"]] == ["2026-05-30", "2026-05-31"]
    assert [d["date"] for d in rdt["rest"]] == ["2026-06-02"]
    assert rdt["best"][0]["active_agents"] == 2

    # All three series must be JSON-serializable for the static dashboard.
    json.dumps({"daily_trends": dt, "top": tops, "rooms": rdt})
