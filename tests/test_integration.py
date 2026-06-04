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
import re

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
    assert {e["agent_name"] for e in events} == {
        "GPT-5.5",
        "Kimi K2.6",
        "Claude Opus 4.8",
    }
    assert all(e["room"] == "best" for e in events)
    # Oldest-first ordering by event_index.
    assert [e["event_index"] for e in events] == [10, 11, 12, 13]

    metrics = analytics.compute_all(events)
    assert metrics["meta"]["total_events"] == 4
    assert metrics["meta"]["total_messages"] == 3  # CONSOLIDATE is not a message
    assert metrics["messages_per_agent"]["GPT-5.5"] == 1
    assert metrics["action_type_breakdown"]["CONSOLIDATE"] == 1
    assert metrics["interaction_graph"] == {
        "Claude Opus 4.8": {"Kimi K2.6": 1},
        "Kimi K2.6": {"GPT-5.5": 1},
    }
    assert metrics["interaction_rankings"] == {
        "top_responders": [
            {"agent": "Claude Opus 4.8", "count": 1},
            {"agent": "Kimi K2.6", "count": 1},
        ],
        "top_targets": [
            {"agent": "GPT-5.5", "count": 1},
            {"agent": "Kimi K2.6", "count": 1},
        ],
    }

    # Hourly heatmap: all three messages fall in the 17:00 UTC bucket.
    heatmap = metrics["hourly_activity_heatmap"]
    assert len(heatmap) == 24
    assert heatmap[17] == 3
    assert sum(heatmap) == 3

    # Response latency: each reply lands 300s after the prior agent's message.
    assert metrics["response_latency"] == [
        {"agent": "Claude Opus 4.8", "median_seconds": 300.0, "responses": 1},
        {"agent": "Kimi K2.6", "median_seconds": 300.0, "responses": 1},
    ]

    # Conversation depth: the three alternating-agent messages form one
    # reply-chain of depth 3 (the trailing CONSOLIDATE is not a message).
    assert metrics["conversation_depth"] == {
        "total_chains": 1,
        "max_depth": 3,
        "mean_depth": 3.0,
        "median_depth": 3.0,
        "depth_distribution": {3: 1},
    }

    # Chain initiators: that single chain was started by the first speaker.
    assert metrics["chain_initiators"] == [{"agent": "GPT-5.5", "chains": 1}]

    # Interaction pairs: the two replies collapse into two undirected
    # partnerships, each alphabetised within the pair.
    assert metrics["top_interaction_pairs"] == [
        {"pair": ["Claude Opus 4.8", "Kimi K2.6"], "count": 1},
        {"pair": ["GPT-5.5", "Kimi K2.6"], "count": 1},
    ]

    output = tmp_path / "dashboard.html"
    resolved = generate(
        metrics, output, {"room": "#best", "days": 1, "version": "0.1.0"}
    )
    html = resolved.read_text(encoding="utf-8")
    assert "Village Pulse — #best" in html
    for name in ("GPT-5.5", "Kimi K2.6", "Claude Opus 4.8"):
        assert name in html

    assert "Agent interactions" in html
    assert "Reply networks" in html
    assert "Top responders" in html
    assert "Top targets" in html
    assert "Reply-adjacency analysis" in html
    assert re.search(r"Claude Opus 4\.8.*?replied to:.*?Kimi K2\.6.*?>1<", html, re.S)
    assert re.search(r"Kimi K2\.6.*?replied to:.*?GPT-5\.5.*?>1<", html, re.S)
    assert "replies made" in html
    assert "replies received" in html
    assert "Activity heatmap" in html
    assert "Response speed" in html
    assert "r-best" not in html
    assert "<script" not in html.lower()


def test_cli_default_html_builds_seven_day_window(tmp_path, monkeypatch):
    """Default HTML report aggregates the seven-day fetch window into trends."""
    captured_kwargs = {}

    def fake_fetch(**kwargs):
        captured_kwargs.update(kwargs)
        return [
            {
                "agent_name": "GPT-5.5",
                "room": "best",
                "created_at": "2026-05-29T17:00:00Z",
                "action_type": "AGENT_TALK",
                "content": "day one",
                "input_tokens": 10,
                "output_tokens": 2,
            },
            {
                "agent_name": "Kimi K2.6",
                "room": "best",
                "created_at": "2026-06-02T17:05:00Z",
                "action_type": "AGENT_TALK",
                "content": "day seven",
                "input_tokens": 20,
                "output_tokens": 4,
            },
        ]

    import village_pulse.api_client as ac  # fresh module (test_cli may have reset sys.modules)

    monkeypatch.setattr(ac, "fetch_events", fake_fetch)
    monkeypatch.setattr(ac.VillageAPIClient, "_discover_latest_day", lambda self: 427)

    from village_pulse.__main__ import main

    out = tmp_path / "digest.html"
    rc = main(["--output", str(out)])

    assert rc == 0
    assert out.exists()
    assert captured_kwargs.get("days") == 7
    assert captured_kwargs.get("current_day") is None
    html = out.read_text(encoding="utf-8")
    assert "Village Pulse - 7-Day Digest" in html
    assert "Window: 7 days" in html
    assert "Activity digest trend (7 days)" in html
    assert "Messages over time (Daily sparkline)" in html
    assert "Agent activity (7-Day Digest)" in html
    assert "Daily trends (7-Day Digest)" in html
    assert "2026-05-29" in html
    assert "2026-06-02" in html
    assert "Messages over time trend" in html
    assert '<svg class="sparkline"' in html
    assert "GPT-5.5" in html and "Kimi K2.6" in html
    assert "<script" not in html.lower()


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
    monkeypatch.setattr(ac.VillageAPIClient, "_discover_latest_day", lambda self: 427)

    from village_pulse.__main__ import main

    out = tmp_path / "report.html"
    rc = main(["--days", "2", "--room", "#best", "--output", str(out)])

    assert rc == 0
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "Village Pulse - 2-Day Digest — #best" in html
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
        "date": "2026-05-30",
        "events": 2,
        "messages": 2,
        "active_agents": 2,
        "input_tokens": 150,
        "output_tokens": 15,
        "total_tokens": 165,
        "efficiency": 10.0,
    }

    # top_agents_over_time: ranked desc, each with oldest-first sparse daily series.
    tops = ca["top_agents_over_time"]
    assert tops[0]["agent"] == "Alice"
    assert tops[0]["total_messages"] == 3
    assert [d["date"] for d in tops[0]["daily"]] == [
        "2026-05-30",
        "2026-05-31",
        "2026-06-02",
    ]

    # room_daily_trends: keyed by room NAME (sorted), each value mirrors daily_trends.
    rdt = ca["room_daily_trends"]
    assert sorted(rdt) == ["best", "rest"]
    assert [d["date"] for d in rdt["best"]] == ["2026-05-30", "2026-05-31"]
    assert [d["date"] for d in rdt["rest"]] == ["2026-06-02"]
    assert rdt["best"][0]["active_agents"] == 2

    # All three series must be JSON-serializable for the static dashboard.
    json.dumps({"daily_trends": dt, "top": tops, "rooms": rdt})


def _flat(agent, room, date, action="AGENT_TALK", content="hi"):
    return {
        "agent_name": agent,
        "room": room,
        "created_at": f"{date}T17:00:00Z",
        "action_type": action,
        "content": content,
    }



def test_integration_empty_events_list_renders_empty_dashboard(tmp_path):
    """Empty input still flows through compute_all -> report without warnings or leaks."""
    metrics = analytics.compute_all([])

    assert metrics["meta"]["total_events"] == 0
    assert metrics["meta"]["total_messages"] == 0
    assert metrics["messages_per_agent"] == {}
    assert metrics["room_participation"] == {}
    assert metrics["interaction_graph"] == {}

    out = tmp_path / "empty.html"
    generate(metrics, out, {"days": 1, "version": "0.1.0"})
    html = out.read_text(encoding="utf-8")

    assert "Village Pulse" in html
    assert "Agent activity" in html
    assert "Raw metrics payload" in html
    assert "<script" not in html.lower()


def test_integration_single_event_pipeline(tmp_path):
    """A one-message dataset keeps singleton counts and has no reply-derived edges."""
    events = [_flat("Solo", "best", "2026-06-01")]
    metrics = analytics.compute_all(events)

    assert metrics["meta"]["total_events"] == 1
    assert metrics["meta"]["total_messages"] == 1
    assert metrics["messages_per_agent"] == {"Solo": 1}
    assert metrics["messages_per_day"] == {"2026-06-01": 1}
    assert metrics["room_participation"] == {"best": {"Solo": 1}}
    assert metrics["interaction_graph"] == {}
    assert metrics["conversation_depth"]["total_chains"] == 0

    out = tmp_path / "single.html"
    generate(metrics, out, {"days": 1, "version": "0.1.0"})
    html = out.read_text(encoding="utf-8")

    assert "Solo" in html
    assert "best" in html
    assert "Agent activity" in html
    assert "<script" not in html.lower()


def test_integration_all_events_from_same_agent(tmp_path):
    """Repeated same-agent messages aggregate but do not create reply chains."""
    events = [
        _flat("Solo", "best", "2026-06-01", content="one"),
        _flat("Solo", "rest", "2026-06-01", content="two"),
        _flat("Solo", "best", "2026-06-02", content="three"),
    ]
    metrics = analytics.compute_all(events)

    assert metrics["meta"]["total_events"] == 3
    assert metrics["messages_per_agent"] == {"Solo": 3}
    assert metrics["messages_per_agent_per_day"] == {
        "Solo": {"2026-06-01": 2, "2026-06-02": 1}
    }
    assert metrics["interaction_graph"] == {}
    assert metrics["response_latency"] == []
    assert metrics["chain_initiators"] == []
    assert metrics["conversation_depth"]["total_chains"] == 0

    out = tmp_path / "same-agent.html"
    generate(metrics, out, {"days": 2, "version": "0.1.0"})
    html = out.read_text(encoding="utf-8")

    assert "Solo" in html
    assert "Room participation" in html
    assert "<script" not in html.lower()


def test_integration_all_events_in_same_room(tmp_path):
    """Single-room activity preserves one room bucket while multi-agent metrics work."""
    events = [
        _flat("Alice", "best", "2026-06-01", content="one"),
        _flat("Bob", "best", "2026-06-01", content="two"),
        _flat("Carol", "best", "2026-06-01", content="three"),
    ]
    metrics = analytics.compute_all(events)

    assert metrics["meta"]["unique_rooms"] == 1
    assert metrics["room_participation"] == {
        "best": {"Alice": 1, "Bob": 1, "Carol": 1}
    }
    assert set(metrics["room_daily_trends"]) == {"best"}
    assert metrics["room_daily_trends"]["best"][0]["active_agents"] == 3
    assert metrics["interaction_graph"] == {"Bob": {"Alice": 1}, "Carol": {"Bob": 1}}

    out = tmp_path / "same-room.html"
    generate(metrics, out, {"room": "best", "days": 1, "version": "0.1.0"})
    html = out.read_text(encoding="utf-8")

    assert "Village Pulse — #best" in html
    assert "Alice" in html and "Bob" in html and "Carol" in html
    assert "rest" not in metrics["room_participation"]
    assert "<script" not in html.lower()


def _day_metrics_from_events(day, events):
    """Mirror archive_compare.generate_comparison_archive's per-day shaping."""
    metrics = analytics.compute_all(events)
    mpa = metrics.get("messages_per_agent", {})
    top = sorted(
        ({"agent": a, "messages": c} for a, c in mpa.items()),
        key=lambda x: x["messages"],
        reverse=True,
    )[:10]
    return {
        "day": day,
        "messages": sum(mpa.values()),
        "events": metrics.get("meta", {}).get("total_events", len(events)),
        "agents": len(mpa),
        "tokens": metrics.get("token_usage", {}).get("totals", {}).get("total", 0),
        "efficiency": metrics.get("token_usage", {})
        .get("totals", {})
        .get("efficiency", 0),
        "room_participation": metrics.get("room_participation", {}),
        "top_agents": top,
        "daily_trends": metrics.get("daily_trends", []),
    }


def test_archive_compare_renders_multiday_dashboard(tmp_path):
    """compute_all -> day_metrics -> generate_comparison produces a clean dashboard."""
    from village_pulse import archive_compare

    day425 = [
        _flat("GPT-5.5", "best", "2026-05-31"),
        _flat("Kimi K2.6", "rest", "2026-05-31"),
        _flat("GPT-5.5", "best", "2026-05-31", content="again"),
    ]
    day426 = [
        _flat("Claude Opus 4.8", "best", "2026-06-01"),
        _flat("GPT-5.5", "rest", "2026-06-01"),
    ]
    day_metrics = [
        _day_metrics_from_events(425, day425),
        _day_metrics_from_events(426, day426),
    ]

    out = tmp_path / "comparison.html"
    archive_compare.generate_comparison(day_metrics, out, village_day=426)
    html = out.read_text(encoding="utf-8")

    # Both days surface in the comparison (multi-point series).
    assert "Day 425" in html and "Day 426" in html
    # Expected section headings render.
    for heading in ("Summary", "Day-by-Day Comparison", "Agent Leaderboard"):
        assert heading in html
    # Agents and rooms render by name.
    for name in ("GPT-5.5", "Kimi K2.6", "Claude Opus 4.8"):
        assert name in html
    assert "best" in html and "rest" in html
    # Multiple SVG charts get drawn from the multi-day series.
    assert html.count("<svg") >= 2
    # No raw UUIDs leak into the rendered dashboard.
    import re

    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", html
    )


def test_archive_compare_escapes_malicious_agent_and_room(tmp_path):
    """archive_compare must HTML-escape agent/room/date strings (no raw markup)."""
    from village_pulse import archive_compare

    evil_agent = '<script>alert("x")</script>'
    evil_room = "<img src=x onerror=alert(1)>"
    events = [
        _flat(evil_agent, evil_room, "2026-05-31"),
        _flat(evil_agent, evil_room, "2026-05-31"),
        _flat("GPT-5.5", evil_room, "2026-05-31"),
    ]
    day_metrics = [_day_metrics_from_events(426, events)]

    out = tmp_path / "comparison.html"
    archive_compare.generate_comparison(day_metrics, out, village_day=426)
    html = out.read_text(encoding="utf-8")

    # No raw injected markup survives (escaped text content is fine).
    assert "<script>" not in html
    assert "<img src=x" not in html
    # Escaped forms are present (agent rendered in leaderboard + bar label).
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def _section(html_text, title):
    """Return the HTML of a named <h2> section up to its closing </table>."""
    needle = f">{title}</h2>"
    i = html_text.find(needle)
    assert i != -1, f"missing section: {title}"
    j = html_text.find("</table>", i)
    return html_text[i:j]


def test_archive_compare_renders_trend_sections_aligned_and_escaped(tmp_path):
    """The new Top Agents / Room Activity sections align multi-day series via
    union_dates+densify (zero-filling absent days) and HTML-escape names."""
    from village_pulse import archive_compare

    evil_agent = "<script>alert(1)</script>"
    day425 = [
        _flat("GPT-5.5", "best", "2026-05-31"),
        _flat("GPT-5.5", "best", "2026-05-31", content="b"),
        _flat("GPT-5.5", "best", "2026-05-31", content="c"),
        _flat("Kimi K2.6", "rest", "2026-05-31"),  # rest only appears on day 425
    ]
    day426 = [
        _flat("GPT-5.5", "best", "2026-06-01"),
        _flat("Claude Opus 4.8", "best", "2026-06-01"),  # Opus only on day 426
        _flat(evil_agent, "best", "2026-06-01"),
    ]
    day_metrics = [
        _day_metrics_from_events(425, day425),
        _day_metrics_from_events(426, day426),
    ]

    out = tmp_path / "comparison.html"
    archive_compare.generate_comparison(day_metrics, out, village_day=426)
    html = out.read_text(encoding="utf-8")

    # Both new sections render after the existing trends section.
    assert '<h2 id="top-agents">Top Agents Over Time</h2>' in html
    assert '<h2 id="room-activity">Room Activity Over Time</h2>' in html

    agents = _section(html, "Top Agents Over Time")
    rooms = _section(html, "Room Activity Over Time")

    # Aggregated totals across the aligned window are correct.
    # GPT-5.5: 3 (day425) + 1 (day426) = 4.
    assert "<td>GPT-5.5</td>" in agents
    assert '<td class="num">4</td>' in agents
    # Rooms: best = 3 + 3 (GPT/Opus/evil on day426) ... best total = 3+1+1+1 = 6, rest = 1.
    assert "<td>best</td>" in rooms
    assert '<td class="num">6</td>' in rooms
    assert "<td>rest</td>" in rooms
    assert '<td class="num">1</td>' in rooms

    # Sparklines drawn per row (best + rest = 2 rooms, several agents).
    assert agents.count("<svg") >= 3
    assert rooms.count("<svg") == 2

    # Malicious agent name is escaped in the new section (no raw markup).
    assert "<script>" not in agents
    assert "&lt;script&gt;" in agents
