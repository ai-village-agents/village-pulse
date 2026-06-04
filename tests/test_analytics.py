"""Unit tests for village_pulse.analytics.

Authored by the analytics module owner (Claude Opus 4.8) to lock down the
metric contracts and the tricky normalization edge cases. Named distinctly so
it complements the broader suite/README work owned by Gemini 3.5 Flash.
"""

from datetime import datetime, timezone

import pytest

from village_pulse import analytics as a
from village_pulse.analytics import ActivityEvent


def _ev(agent, room, action, when, content=""):
    return {
        "agentName": agent,
        "roomId": room,
        "actionType": action,
        "createdAt": when,
        "content": content,
    }


@pytest.fixture
def sample_raw():
    """A small, deterministic mix of rooms, agents, days, and action types."""
    return [
        _ev("Alice", "#best", "AGENT_TALK", "2026-06-01T09:00:00Z", "hi"),
        _ev("Alice", "#best", "AGENT_TALK", "2026-06-01T10:30:00Z", "again"),
        _ev("Bob", "#best", "AGENT_TALK", "2026-06-01T09:15:00Z", "hello"),
        _ev("Bob", "#rest", "AGENT_TALK", "2026-05-31T23:00:00Z", "yesterday"),
        _ev("Alice", "#best", "PAUSE", "2026-06-01T10:31:00Z"),
        {
            "userName": "admin",
            "roomId": "#best",
            "actionType": "USER_TALK",
            "createdAt": "2026-06-01T11:00:00Z",
            "content": "note",
        },
    ]


# --- normalization -------------------------------------------------------


def test_normalize_basic_fields(sample_raw):
    events = a.normalize_events(sample_raw)
    assert len(events) == 6
    assert events[0].agent == "Alice"
    assert events[0].room == "#best"
    assert events[0].action_type == "AGENT_TALK"
    assert events[0].is_message is True
    assert events[4].is_message is False  # PAUSE


def test_normalize_user_alias():
    [e] = a.normalize_events([{"userName": "admin", "actionType": "user_talk"}])
    assert e.agent == "admin"
    assert e.action_type == "USER_TALK"  # upper-cased


def test_normalize_is_idempotent(sample_raw):
    once = a.normalize_events(sample_raw)
    twice = a.normalize_events(once)
    assert once == twice


@pytest.mark.parametrize(
    "value,expected_year",
    [
        ("2026-06-01T09:00:00Z", 2026),
        ("2026-06-01T09:00:00+00:00", 2026),
        ("2026-06-01 09:00:00", 2026),
        (1700000000, 2023),  # epoch seconds
        (1700000000000, 2023),  # epoch milliseconds
        (datetime(2026, 6, 1, tzinfo=timezone.utc), 2026),
    ],
)
def test_timestamp_formats(value, expected_year):
    [e] = a.normalize_events([{"agentName": "X", "createdAt": value}])
    assert e.timestamp is not None
    assert e.timestamp.tzinfo is not None
    assert e.timestamp.year == expected_year


def test_unparseable_timestamp_is_none():
    [e] = a.normalize_events([{"agentName": "X", "createdAt": "not a date"}])
    assert e.timestamp is None
    assert e.date_iso is None


def test_missing_fields_are_safe():
    [e] = a.normalize_events([{}])
    assert e.agent == ""
    assert e.room is None
    assert e.action_type == ""
    assert e.timestamp is None


# --- metrics -------------------------------------------------------------


def test_messages_per_agent_excludes_nonmessages(sample_raw):
    result = a.messages_per_agent(a.normalize_events(sample_raw))
    # Alice 2 AGENT_TALK (PAUSE excluded), Bob 2, admin 1
    assert result == {"Alice": 2, "Bob": 2, "admin": 1}
    # Ordering contract: count-descending, ties broken by agent name ascending.
    # The dict ``==`` above ignores key order, so lock it explicitly. Alice and
    # Bob tie at 2 -> name-asc puts Alice first; admin (count 1) comes last.
    assert list(result.keys()) == ["Alice", "Bob", "admin"]


def test_messages_per_agent_counts_all_when_not_message_only(sample_raw):
    result = a.messages_per_agent(a.normalize_events(sample_raw), message_only=False)
    assert result["Alice"] == 3  # includes the PAUSE


def test_messages_per_agent_per_day(sample_raw):
    result = a.messages_per_agent_per_day(a.normalize_events(sample_raw))
    assert result["Bob"] == {"2026-05-31": 1, "2026-06-01": 1}
    assert result["Alice"] == {"2026-06-01": 2}
    # Ordering contract (documented in docs/analytics_contract.md): the outer
    # agent keys are name-sorted and each agent's inner date keys are
    # chronological. The dict ``==`` checks above ignore key order, so assert the
    # orderings explicitly to regression-lock the documented behaviour.
    assert list(result.keys()) == sorted(result.keys())
    assert list(result["Bob"].keys()) == ["2026-05-31", "2026-06-01"]


def test_messages_per_day_is_sorted(sample_raw):
    result = a.messages_per_day(a.normalize_events(sample_raw))
    assert list(result.keys()) == ["2026-05-31", "2026-06-01"]
    assert result["2026-06-01"] == 4  # Alice x2, Bob x1, admin x1


def test_action_type_breakdown(sample_raw):
    result = a.action_type_breakdown(a.normalize_events(sample_raw))
    assert result["AGENT_TALK"] == 4
    assert result["PAUSE"] == 1
    assert result["USER_TALK"] == 1
    # Ordering contract: count-descending (the Markdown export and HTML
    # dashboard render both depend on this insertion order).
    counts = list(result.values())
    assert counts == sorted(counts, reverse=True)


def test_action_type_breakdown_orders_ties_by_name_and_handles_empty():
    # Ties on count must fall back to action-type name ascending.
    norm = a.normalize_events(
        [
            _ev("Alice", "#best", "ZED_ACTION", "2026-01-01T00:00:00Z"),
            _ev("Bob", "#best", "ALPHA_ACTION", "2026-01-01T00:01:00Z"),
        ]
    )
    result = a.action_type_breakdown(norm)
    assert list(result.keys()) == ["ALPHA_ACTION", "ZED_ACTION"]
    # Empty input yields an empty mapping.
    assert a.action_type_breakdown([]) == {}


def test_room_participation(sample_raw):
    result = a.room_participation(a.normalize_events(sample_raw))
    assert result["#best"]["Alice"] == 2
    assert result["#rest"] == {"Bob": 1}
    # Ordering contract (docs/analytics_contract.md): rooms are name-sorted and
    # within each room agents are count-descending then name-ascending. Asserted
    # explicitly because the dict checks above ignore key order. In #best, Bob
    # and admin tie at 1 -> name-asc puts Bob before admin.
    assert list(result.keys()) == ["#best", "#rest"]
    assert list(result["#best"].keys()) == ["Alice", "Bob", "admin"]


def test_room_participation_rates_sum_to_one(sample_raw):
    rates = a.room_participation_rates(a.normalize_events(sample_raw))
    for room, agents in rates.items():
        assert abs(sum(agents.values()) - 1.0) < 1e-6, room
    # Rates inherit room_participation's ordering (rooms name-sorted; agents by
    # descending share, i.e. count, then name). Lock it explicitly.
    assert list(rates.keys()) == ["#best", "#rest"]
    assert list(rates["#best"].keys()) == ["Alice", "Bob", "admin"]


def test_busiest_hours_zero_filled(sample_raw):
    hours = a.busiest_hours(a.normalize_events(sample_raw))
    assert len(hours) == 24
    assert hours[9] == 2  # 09:00 and 09:15
    assert hours[11] == 1
    assert hours[0] == 0


def test_hourly_activity_heatmap_is_24_element_list(sample_raw):
    heat = a.hourly_activity_heatmap(a.normalize_events(sample_raw))
    assert isinstance(heat, list)
    assert len(heat) == 24
    assert heat[9] == 2  # 09:00 and 09:15
    assert heat[11] == 1
    assert heat[0] == 0
    assert sum(heat) == 5  # five message events with timestamps


def test_hourly_activity_heatmap_matches_busiest_hours(sample_raw):
    events = a.normalize_events(sample_raw)
    heat = a.hourly_activity_heatmap(events)
    hours = a.busiest_hours(events)
    assert heat == [hours[h] for h in range(24)]


def test_hourly_activity_heatmap_empty_is_all_zero():
    heat = a.hourly_activity_heatmap([])
    assert heat == [0] * 24


def test_response_latency_basic(sample_raw):
    # In #best: Bob answers Alice after 15min (900s); admin answers Alice
    # after 30min (1800s). The 75min Bob->Alice gap and the lone #rest
    # message produce no qualifying responses.
    rows = a.response_latency(sample_raw)
    assert rows == [
        {"agent": "Bob", "median_seconds": 900.0, "responses": 1},
        {"agent": "admin", "median_seconds": 1800.0, "responses": 1},
    ]


def test_response_latency_respects_window(sample_raw):
    # A 20-minute window keeps Bob's 15min reply but drops admin's 30min one.
    rows = a.response_latency(sample_raw, window_minutes=20)
    assert rows == [
        {"agent": "Bob", "median_seconds": 900.0, "responses": 1},
    ]


def test_response_latency_empty_is_empty_list():
    assert a.response_latency([]) == []


def test_conversation_depth_basic(sample_raw):
    # In #best: Alice->Bob (09:00->09:15) is a depth-2 chain; the 75min gap
    # breaks it, then Alice->admin (10:30->11:00, exactly 30min) is another
    # depth-2 chain. The PAUSE and the lone #rest message are ignored.
    assert a.conversation_depth(sample_raw) == {
        "total_chains": 2,
        "max_depth": 2,
        "mean_depth": 2.0,
        "median_depth": 2.0,
        "depth_distribution": {2: 2},
    }


def test_conversation_depth_respects_window(sample_raw):
    # A 20-minute window drops the exactly-30min Alice->admin link, leaving
    # only the single Alice->Bob chain.
    assert a.conversation_depth(sample_raw, window_minutes=20) == {
        "total_chains": 1,
        "max_depth": 2,
        "mean_depth": 2.0,
        "median_depth": 2.0,
        "depth_distribution": {2: 1},
    }


def test_conversation_depth_alternating_run_and_repeat_reset():
    # A,B,A,B within window is one depth-4 chain. A repeated speaker breaks
    # the chain; the following A->? starts a fresh depth-2 chain.
    raw = [
        _ev("A", "r", "AGENT_TALK", "2026-06-01T09:00:00Z"),
        _ev("B", "r", "AGENT_TALK", "2026-06-01T09:05:00Z"),
        _ev("A", "r", "AGENT_TALK", "2026-06-01T09:10:00Z"),
        _ev("B", "r", "AGENT_TALK", "2026-06-01T09:15:00Z"),
        _ev("B", "r", "AGENT_TALK", "2026-06-01T09:20:00Z"),  # repeat -> break
        _ev("A", "r", "AGENT_TALK", "2026-06-01T09:25:00Z"),
    ]
    result = a.conversation_depth(raw)
    assert result["max_depth"] == 4
    assert result["total_chains"] == 2
    assert result["depth_distribution"] == {2: 1, 4: 1}


def test_conversation_depth_empty_is_zeroed():
    assert a.conversation_depth([]) == {
        "total_chains": 0,
        "max_depth": 0,
        "mean_depth": 0.0,
        "median_depth": 0.0,
        "depth_distribution": {},
    }


def test_chain_initiators_basic(sample_raw):
    # Both #best chains (Alice->Bob, then Alice->admin) are started by Alice.
    assert a.chain_initiators(sample_raw) == [{"agent": "Alice", "chains": 2}]


def test_chain_initiators_tie_ordering():
    # A,B,A,B is one chain started by A; the repeated B breaks it and the
    # trailing B->A is a second chain started by B. Ties on count sort by name.
    raw = [
        _ev("A", "r", "AGENT_TALK", "2026-06-01T09:00:00Z"),
        _ev("B", "r", "AGENT_TALK", "2026-06-01T09:05:00Z"),
        _ev("A", "r", "AGENT_TALK", "2026-06-01T09:10:00Z"),
        _ev("B", "r", "AGENT_TALK", "2026-06-01T09:15:00Z"),
        _ev("B", "r", "AGENT_TALK", "2026-06-01T09:20:00Z"),  # repeat -> break
        _ev("A", "r", "AGENT_TALK", "2026-06-01T09:25:00Z"),
    ]
    assert a.chain_initiators(raw) == [
        {"agent": "A", "chains": 1},
        {"agent": "B", "chains": 1},
    ]


def test_chain_initiators_total_matches_chain_count(sample_raw):
    # Every chain has exactly one initiator, so the counts must sum to the
    # conversation_depth total_chains.
    ci = a.chain_initiators(sample_raw)
    total = a.conversation_depth(sample_raw)["total_chains"]
    assert sum(r["chains"] for r in ci) == total


def test_chain_initiators_empty():
    assert a.chain_initiators([]) == []


def test_top_interaction_pairs_basic(sample_raw):
    # Bob->Alice (1 reply) and admin->Alice (1 reply) collapse into two
    # undirected partnerships, each alphabetised within the pair.
    assert a.top_interaction_pairs(a.normalize_events(sample_raw)) == [
        {"pair": ["Alice", "Bob"], "count": 1},
        {"pair": ["Alice", "admin"], "count": 1},
    ]


def test_top_interaction_pairs_sums_both_directions():
    # A->B and B->A replies count toward the same partnership.
    raw = [
        _ev("A", "r", "AGENT_TALK", "2026-06-01T09:00:00Z"),
        _ev("B", "r", "AGENT_TALK", "2026-06-01T09:05:00Z"),  # B replies to A
        _ev("A", "r", "AGENT_TALK", "2026-06-01T09:10:00Z"),  # A replies to B
    ]
    assert a.top_interaction_pairs(a.normalize_events(raw)) == [
        {"pair": ["A", "B"], "count": 2},
    ]


def test_top_interaction_pairs_matches_graph_edge_total(sample_raw):
    # Every directed edge belongs to exactly one undirected pair, so the pair
    # counts must sum to the total number of directed edges in the graph.
    events = a.normalize_events(sample_raw)
    graph = a.interaction_graph(events)
    edge_total = sum(c for targets in graph.values() for c in targets.values())
    pairs = a.top_interaction_pairs(events)
    assert sum(r["count"] for r in pairs) == edge_total
    # pairs are alphabetised within each row and sorted by count then pair
    assert all(r["pair"] == sorted(r["pair"]) for r in pairs)
    assert pairs == sorted(pairs, key=lambda r: (-r["count"], r["pair"]))


def test_top_interaction_pairs_empty():
    assert a.top_interaction_pairs([]) == []


def test_busiest_weekdays_zero_filled(sample_raw):
    wd = a.busiest_weekdays(a.normalize_events(sample_raw))
    assert len(wd) == 7
    assert sum(wd.values()) == 5  # five message events with timestamps


def test_agent_last_seen_orders_recent_first(sample_raw):
    seen = a.agent_last_seen(a.normalize_events(sample_raw))
    assert list(seen.keys())[0] == "admin"  # 11:00 is latest
    assert seen["Bob"].isoformat().startswith("2026-06-01")


def test_active_agents_window(sample_raw):
    events = a.normalize_events(sample_raw)
    # reference = latest (admin 11:00 on 06-01); 24h window keeps 06-01 activity
    result = a.active_agents(events, window_hours=24)
    assert set(result["active"]) == {"Alice", "Bob", "admin"}
    # a 1-hour window should drop the 09:00-09:15 talkers
    tight = a.active_agents(events, window_hours=1)
    assert "admin" in tight["active"]
    assert "Bob" in tight["inactive"] or "Bob" not in tight["active"]


def test_room_health_shape(sample_raw):
    health = a.room_health(a.normalize_events(sample_raw))
    assert health["#best"]["messages"] == 4
    assert health["#best"]["unique_agents"] == 3
    assert "last_activity" in health["#best"]
    assert "messages_in_window" in health["#best"]


# --- compute_all ---------------------------------------------------------


def test_compute_all_keys_and_serializable(sample_raw):
    import json

    summary = a.compute_all(sample_raw)
    expected = {
        "meta",
        "messages_per_agent",
        "messages_per_agent_per_day",
        "messages_per_day",
        "action_type_breakdown",
        "room_participation",
        "room_participation_rates",
        "busiest_hours",
        "busiest_weekdays",
        "agent_last_seen",
        "active_agents",
        "room_health",
        "token_usage",
        "daily_trends",
        "agent_daily_trends",
        "top_agents_over_time",
        "room_daily_trends",
        "interaction_graph",
        "interaction_rankings",
        "top_interaction_pairs",
        "hourly_activity_heatmap",
        "response_latency",
        "conversation_depth",
        "chain_initiators",
    }
    assert set(summary.keys()) == expected
    json.dumps(summary)  # must not raise


def test_compute_all_meta(sample_raw):
    meta = a.compute_all(sample_raw)["meta"]
    assert meta["total_events"] == 6
    assert meta["total_messages"] == 5
    assert meta["unique_agents"] == 3
    assert meta["unique_rooms"] == 2
    assert meta["earliest_event"].startswith("2026-05-31")
    assert meta["latest_event"].startswith("2026-06-01")


def test_compute_all_empty_input():
    import json

    summary = a.compute_all([])
    assert summary["meta"]["total_events"] == 0
    assert summary["active_agents"] == {"active": [], "inactive": []}
    json.dumps(summary)


def test_compute_all_accepts_activityevent_objects(sample_raw):
    events = a.normalize_events(sample_raw)
    assert all(isinstance(e, ActivityEvent) for e in events)
    summary = a.compute_all(events)  # pre-normalized input also works
    assert summary["meta"]["total_events"] == 6


# --- token usage ---------------------------------------------------------


def _tok_ev(agent, room, inp, out, action="AGENT_TALK", when="2026-06-01T09:00:00Z"):
    return {
        "agentName": agent,
        "roomId": room,
        "actionType": action,
        "createdAt": when,
        "inputTokens": inp,
        "outputTokens": out,
    }


@pytest.fixture
def token_raw():
    return [
        _tok_ev("Alice", "#best", 100, 10, when="2026-06-01T09:00:00Z"),
        _tok_ev("Alice", "#best", 300, 20, when="2026-06-02T09:00:00Z"),
        _tok_ev("Bob", "#rest", 50, 25, when="2026-06-01T09:00:00Z"),
        # event with no token fields at all is ignored by token metrics
        _ev("Carol", "#best", "AGENT_TALK", "2026-06-01T09:00:00Z", "hi"),
    ]


def test_normalize_extracts_tokens():
    [e] = a.normalize_events([_tok_ev("X", "#best", 120, 30)])
    assert e.input_tokens == 120
    assert e.output_tokens == 30
    assert e.total_tokens == 150


def test_normalize_tokens_absent_is_none():
    [e] = a.normalize_events([_ev("X", "#best", "AGENT_TALK", "2026-06-01T09:00:00Z")])
    assert e.input_tokens is None
    assert e.output_tokens is None
    assert e.total_tokens == 0


def test_coerce_int_rejects_junk():
    assert a._coerce_int(None) is None
    assert a._coerce_int(True) is None
    assert a._coerce_int(-5) is None
    assert a._coerce_int("nope") is None
    assert a._coerce_int("42") == 42
    assert a._coerce_int(7.9) == 7


def test_tokens_per_agent(token_raw):
    result = a.tokens_per_agent(a.normalize_events(token_raw))
    assert list(result.keys()) == [
        "Alice",
        "Bob",
    ]  # Carol has no tokens; sorted by total
    assert result["Alice"] == {
        "input": 400,
        "output": 30,
        "total": 430,
        "efficiency": round(400 / 30, 2),
    }
    assert result["Bob"]["total"] == 75


def test_tokens_per_room(token_raw):
    result = a.tokens_per_room(a.normalize_events(token_raw))
    assert result["#best"]["input"] == 400
    assert result["#rest"]["total"] == 75


def test_tokens_per_day(token_raw):
    result = a.tokens_per_day(a.normalize_events(token_raw))
    assert list(result.keys()) == ["2026-06-01", "2026-06-02"]  # chronological
    assert result["2026-06-01"]["input"] == 150  # Alice 100 + Bob 50
    assert result["2026-06-02"]["input"] == 300


def test_token_totals(token_raw):
    totals = a.token_totals(a.normalize_events(token_raw))
    assert totals["input"] == 450
    assert totals["output"] == 55
    assert totals["total"] == 505
    assert totals["events_with_tokens"] == 3
    assert totals["efficiency"] == round(450 / 55, 2)


def test_token_efficiency_none_when_no_output():
    result = a.tokens_per_agent(a.normalize_events([_tok_ev("Z", "#best", 99, 0)]))
    assert result["Z"]["efficiency"] is None


def test_compute_all_includes_token_usage(token_raw):
    import json

    tu = a.compute_all(token_raw)["token_usage"]
    assert set(tu.keys()) == {"totals", "per_agent", "per_room", "per_day"}
    assert tu["totals"]["total"] == 505
    json.dumps(tu)


def test_compute_all_meta_token_totals(token_raw):
    meta = a.compute_all(token_raw)["meta"]
    assert meta["total_input_tokens"] == 450
    assert meta["total_output_tokens"] == 55


def test_daily_trends_ordering_and_fields(token_raw):
    import json

    series = a.daily_trends(a.normalize_events(token_raw))
    # one entry per day with events, oldest-first
    assert [d["date"] for d in series] == ["2026-06-01", "2026-06-02"]
    d1, d2 = series
    # 2026-06-01: Alice 100/10, Bob 50/25, Carol (no tokens) -> 3 events/agents
    assert d1["events"] == 3
    assert d1["messages"] == 3
    assert d1["active_agents"] == 3
    assert d1["input_tokens"] == 150
    assert d1["output_tokens"] == 35
    assert d1["total_tokens"] == 185
    assert d1["efficiency"] == round(150 / 35, 2)
    # 2026-06-02: only Alice 300/20
    assert d2["events"] == 1
    assert d2["active_agents"] == 1
    assert d2["total_tokens"] == 320
    json.dumps(series)  # must be serializable


def test_daily_trends_empty_and_in_compute_all():
    assert a.daily_trends([]) == []
    summary = a.compute_all([])
    assert summary["daily_trends"] == []


def test_agent_daily_trends(token_raw):
    import json

    events = a.normalize_events(token_raw)
    alice = a.agent_daily_trends(events, "Alice")
    assert [d["date"] for d in alice] == ["2026-06-01", "2026-06-02"]
    assert alice[0] == {
        "date": "2026-06-01",
        "messages": 1,
        "input_tokens": 100,
        "output_tokens": 10,
    }
    assert alice[1] == {
        "date": "2026-06-02",
        "messages": 1,
        "input_tokens": 300,
        "output_tokens": 20,
    }
    # Bob only appears on one day; Carol has no tokens but is still a message.
    bob = a.agent_daily_trends(events, "Bob")
    assert bob == [
        {"date": "2026-06-01", "messages": 1, "input_tokens": 50, "output_tokens": 25}
    ]
    carol = a.agent_daily_trends(events, "Carol")
    assert carol == [
        {"date": "2026-06-01", "messages": 1, "input_tokens": 0, "output_tokens": 0}
    ]
    # Unknown agent and empty input both yield an empty series.
    assert a.agent_daily_trends(events, "Nobody") == []
    assert a.agent_daily_trends([], "Alice") == []
    json.dumps(alice)  # must be serializable


def test_top_agents_over_time(token_raw):
    import json

    events = a.normalize_events(token_raw)
    top = a.top_agents_over_time(events, top_n=2)
    # Ranked by total messages (Alice 2, then Bob/Carol 1 -> name tiebreak).
    assert [row["agent"] for row in top] == ["Alice", "Bob"]
    assert top[0]["total_messages"] == 2
    assert top[0]["daily"] == a.agent_daily_trends(events, "Alice")
    assert top[1]["total_messages"] == 1
    # top_n larger than agent count just returns everyone with messages.
    everyone = a.top_agents_over_time(events, top_n=10)
    assert {row["agent"] for row in everyone} == {"Alice", "Bob", "Carol"}
    # Edge cases: empty input and non-positive top_n.
    assert a.top_agents_over_time([]) == []
    assert a.top_agents_over_time(events, top_n=0) == []
    json.dumps(top)


def test_room_daily_trends(token_raw):
    events = a.normalize_events(token_raw)
    best = a.room_daily_trends(events, "#best")
    assert [d["date"] for d in best] == ["2026-06-01", "2026-06-02"]
    # 06-01 in #best: Alice (100/10) + Carol (no tokens), both messages
    assert best[0] == {
        "date": "2026-06-01",
        "events": 2,
        "messages": 2,
        "active_agents": 2,
        "input_tokens": 100,
        "output_tokens": 10,
    }
    assert best[1] == {
        "date": "2026-06-02",
        "events": 1,
        "messages": 1,
        "active_agents": 1,
        "input_tokens": 300,
        "output_tokens": 20,
    }
    rest = a.room_daily_trends(events, "#rest")
    assert rest == [
        {
            "date": "2026-06-01",
            "events": 1,
            "messages": 1,
            "active_agents": 1,
            "input_tokens": 50,
            "output_tokens": 25,
        }
    ]
    assert a.room_daily_trends(events, "#nowhere") == []
    assert a.room_daily_trends([], "#best") == []
    # wired into compute_all for all rooms, empty -> {}
    summary = a.compute_all(token_raw)
    assert summary["room_daily_trends"]["#best"] == best
    assert a.compute_all([])["room_daily_trends"] == {}


def test_agent_trends_in_compute_all(token_raw):
    summary = a.compute_all(token_raw)
    assert summary["agent_daily_trends"]["Alice"] == a.agent_daily_trends(
        a.normalize_events(token_raw), "Alice"
    )
    assert [r["agent"] for r in summary["top_agents_over_time"]][0] == "Alice"
    empty = a.compute_all([])
    assert empty["agent_daily_trends"] == {}
    assert empty["top_agents_over_time"] == []


def test_union_dates_merges_sorts_and_dedupes():
    s1 = [{"date": "2026-05-28"}, {"date": "2026-05-26"}]
    s2 = [{"date": "2026-05-28"}, {"date": "2026-06-01"}]
    assert a.union_dates(s1, s2) == ["2026-05-26", "2026-05-28", "2026-06-01"]


def test_union_dates_ignores_none_empty_and_missing_dates():
    assert a.union_dates(None, [], [{"messages": 1}]) == []
    assert a.union_dates([{"date": "2026-06-01"}], None) == ["2026-06-01"]


def test_densify_zero_fills_gaps_and_copies_fields():
    axis = ["2026-05-26", "2026-05-27", "2026-06-01"]
    series = [
        {"date": "2026-05-26", "messages": 5, "total_tokens": 50},
        {"date": "2026-06-01", "messages": 3, "total_tokens": 30},
    ]
    out = a.densify(series, axis, ["messages", "total_tokens"])
    assert [r["date"] for r in out] == axis
    assert [r["messages"] for r in out] == [5, 0, 3]
    assert [r["total_tokens"] for r in out] == [50, 0, 30]
    # only requested fields plus date are present
    assert set(out[0]) == {"date", "messages", "total_tokens"}


def test_densify_none_series_is_all_zero():
    axis = ["2026-05-26", "2026-05-27"]
    out = a.densify(None, axis, ["messages"])
    assert out == [
        {"date": "2026-05-26", "messages": 0},
        {"date": "2026-05-27", "messages": 0},
    ]


def test_densify_missing_field_defaults_zero():
    axis = ["2026-05-26"]
    out = a.densify(
        [{"date": "2026-05-26", "messages": 7}], axis, ["messages", "events"]
    )
    assert out == [{"date": "2026-05-26", "messages": 7, "events": 0}]


def test_lookup_from_objects():
    class DummyObj:
        def __init__(self):
            self.foo = "bar"

    obj = DummyObj()
    assert a._lookup(obj, ["foo"]) == "bar"


def test_coerce_timestamp_exceptions():
    assert a._coerce_timestamp("   ") is None
    assert a._coerce_timestamp(1e20) is None


def test_room_participation_rates_zero():
    assert a.room_participation_rates([]) == {}


def test_room_participation_rates_zero_total():
    from unittest import mock

    with mock.patch(
        "village_pulse.analytics.room_participation",
        return_value={"empty_room": {"agent1": 0}},
    ):
        assert a.room_participation_rates([], message_only=False) == {}


def test_reference_time_empty():
    assert a._reference_time([], None) is None


def test_room_health_no_cutoff():
    event = a.ActivityEvent(
        agent="Alice",
        room="best",
        timestamp=None,
        action_type="AGENT_TALK",
        content="hello",
        input_tokens=None,
        output_tokens=None,
    )
    health = a.room_health([event], reference_time=None)
    assert health["best"]["messages_in_window"] == 0


def test_multi_room_alignment_recipe_from_compute_all():
    """Lock down the documented union_dates+densify recipe on real compute_all output.

    docs/analytics_contract.md advertises building one shared axis across
    daily_trends + every room series, then zero-filling each. Each room here is
    deliberately sparse on a different day so the union axis must span all days
    and the gaps must zero-fill — guarding the recipe against analytics drift.
    """
    raw = [
        _ev("Alice", "#best", "AGENT_TALK", "2026-05-26T09:00:00Z", "a"),
        _ev("Bob", "#rest", "AGENT_TALK", "2026-05-28T09:00:00Z", "b"),
        _ev("Alice", "#best", "AGENT_TALK", "2026-05-29T09:00:00Z", "c"),
        _ev("Bob", "#rest", "AGENT_TALK", "2026-05-29T10:00:00Z", "d"),
    ]
    summary = a.compute_all(raw)
    daily_trends = summary["daily_trends"]
    rdt = summary["room_daily_trends"]

    # Each room is sparse with a gap on a different day.
    assert [r["date"] for r in rdt["#best"]] == ["2026-05-26", "2026-05-29"]
    assert [r["date"] for r in rdt["#rest"]] == ["2026-05-28", "2026-05-29"]

    # The documented recipe, verbatim.
    axis = a.union_dates(daily_trends, *rdt.values())
    overall = a.densify(daily_trends, axis, ["messages", "total_tokens"])
    rooms = {name: a.densify(rows, axis, ["messages"]) for name, rows in rdt.items()}

    assert axis == ["2026-05-26", "2026-05-28", "2026-05-29"]
    # Every aligned series shares the axis: same length, same dates, in order.
    for series in (overall, rooms["#best"], rooms["#rest"]):
        assert [row["date"] for row in series] == axis

    # Gaps zero-fill; present days carry the real counts.
    assert [r["messages"] for r in rooms["#best"]] == [1, 0, 1]
    assert [r["messages"] for r in rooms["#rest"]] == [0, 1, 1]
    # Overall equals the per-room sum on every aligned day.
    assert [r["messages"] for r in overall] == [1, 1, 2]


class TestNormalizationEdgeCases:
    """Cover the harder-to-reach normalization and helper branches so the
    defensive code paths stay verified (analytics is the owner's lane)."""

    def test_lookup_peeks_into_nested_data_mapping(self):
        # Top-level carries the agent; room/content live only in nested ``data``.
        ev = a.normalize_event(
            {
                "agentName": "Alice",
                "data": {"room": "#best", "content": "hello from nested"},
                "actionType": "AGENT_TALK",
            }
        )
        assert ev.agent == "Alice"
        assert ev.room == "#best"
        assert ev.content == "hello from nested"

    def test_lookup_peeks_into_nested_details_mapping(self):
        ev = a.normalize_event(
            {
                "agentName": "Bob",
                "details": {"content": "hi from details"},
                "actionType": "AGENT_TALK",
            }
        )
        assert ev.content == "hi from details"

    def test_numeric_string_epoch_seconds(self):
        ts = a._coerce_timestamp("1716742800")
        assert ts is not None
        assert ts.tzinfo is not None
        assert (ts.year, ts.month, ts.day) == (2024, 5, 26)

    def test_numeric_string_epoch_milliseconds(self):
        ts = a._coerce_timestamp("1716742800000")
        assert ts is not None
        assert ts.year == 2024

    def test_human_feed_format_parses_as_wall_clock_utc(self):
        # ISO parsing rejects this, so it falls through to the strptime formats.
        # Drop the tz abbreviation: "%Z" recognition of names like "PDT" is
        # platform/locale dependent, so we use the tz-free human format which
        # the parser treats as wall-clock UTC.
        ts = a._coerce_timestamp("6/1/2026, 10:04:07 AM")
        assert ts == datetime(2026, 6, 1, 10, 4, 7, tzinfo=timezone.utc)

    def test_plain_datetime_format_without_timezone(self):
        ts = a._coerce_timestamp("2026/06/01 10:04:07")
        # Either parsed via strptime fallback or None, but must be tz-aware if set.
        if ts is not None:
            assert ts.tzinfo is not None

    def test_reference_time_explicit_naive_is_coerced_to_utc(self):
        naive = datetime(2026, 6, 1, 10, 0, 0)
        resolved = a._reference_time([], naive)
        assert resolved == datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert resolved.tzinfo is not None

    def test_reference_time_explicit_aware_is_preserved(self):
        aware = datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert a._reference_time([], aware) == aware


class TestInteractionGraph:
    """Reply-adjacency: who responds to whom within a room/window."""

    def test_basic_direction_and_counts(self):
        evs = a.normalize_events(
            [
                _ev("Lead", "#best", "AGENT_TALK", "2026-06-02T17:00:00Z"),
                _ev("Opus", "#best", "AGENT_TALK", "2026-06-02T17:05:00Z"),
                _ev("Lead", "#best", "AGENT_TALK", "2026-06-02T17:10:00Z"),
            ]
        )
        g = a.interaction_graph(evs)
        # Opus replied to Lead once; Lead replied to Opus once.
        assert g == {"Lead": {"Opus": 1}, "Opus": {"Lead": 1}}

    def test_same_agent_consecutive_is_skipped(self):
        evs = a.normalize_events(
            [
                _ev("Opus", "#best", "AGENT_TALK", "2026-06-02T17:00:00Z"),
                _ev("Opus", "#best", "AGENT_TALK", "2026-06-02T17:01:00Z"),
                _ev("Lead", "#best", "AGENT_TALK", "2026-06-02T17:02:00Z"),
            ]
        )
        # Only Lead-after-Opus counts; the Opus->Opus pair is ignored.
        assert a.interaction_graph(evs) == {"Lead": {"Opus": 1}}

    def test_window_excludes_far_apart_messages(self):
        evs = a.normalize_events(
            [
                _ev("Lead", "#best", "AGENT_TALK", "2026-06-02T17:00:00Z"),
                _ev("Opus", "#best", "AGENT_TALK", "2026-06-02T19:00:00Z"),
            ]
        )
        assert a.interaction_graph(evs, window_minutes=30.0) == {}
        # Widen the window and the adjacency reappears.
        assert a.interaction_graph(evs, window_minutes=180.0) == {"Opus": {"Lead": 1}}

    def test_rooms_are_isolated(self):
        evs = a.normalize_events(
            [
                _ev("Lead", "#best", "AGENT_TALK", "2026-06-02T17:00:00Z"),
                _ev("Opus", "#rest", "AGENT_TALK", "2026-06-02T17:01:00Z"),
            ]
        )
        # Different rooms never form an adjacency.
        assert a.interaction_graph(evs) == {}

    def test_targets_sorted_by_count_desc_then_name(self):
        evs = a.normalize_events(
            [
                _ev("Lead", "#best", "AGENT_TALK", "2026-06-02T17:00:00Z"),
                _ev("Opus", "#best", "AGENT_TALK", "2026-06-02T17:01:00Z"),
                _ev("Gem", "#best", "AGENT_TALK", "2026-06-02T17:02:00Z"),
                _ev("Opus", "#best", "AGENT_TALK", "2026-06-02T17:03:00Z"),
                _ev("Lead", "#best", "AGENT_TALK", "2026-06-02T17:04:00Z"),
                _ev("Opus", "#best", "AGENT_TALK", "2026-06-02T17:05:00Z"),
            ]
        )
        g = a.interaction_graph(evs)
        # Opus replied to Lead twice and Gem once -> Lead first (higher count).
        assert list(g["Opus"].keys()) == ["Lead", "Gem"]
        assert g["Opus"] == {"Lead": 2, "Gem": 1}

    def test_empty_input(self):
        assert a.interaction_graph([]) == {}

    def test_message_only_false_counts_all_actions(self):
        evs = a.normalize_events(
            [
                _ev("Lead", "#best", "AGENT_TALK", "2026-06-02T17:00:00Z"),
                _ev("Opus", "#best", "PAUSE", "2026-06-02T17:01:00Z"),
            ]
        )
        # Default (messages only) ignores the PAUSE.
        assert a.interaction_graph(evs) == {}
        # message_only=False treats every action as activity.
        assert a.interaction_graph(evs, message_only=False) == {"Opus": {"Lead": 1}}

    def test_undated_messages_are_ignored(self):
        evs = a.normalize_events(
            [
                _ev("Lead", "#best", "AGENT_TALK", "not-a-real-timestamp"),
                _ev("Opus", "#best", "AGENT_TALK", "2026-06-02T17:00:00Z"),
                _ev("Lead", "#best", "AGENT_TALK", "2026-06-02T17:05:00Z"),
            ]
        )
        # The undated Lead message is dropped, so only Lead-after-Opus remains.
        assert any(e.timestamp is None for e in evs)
        assert a.interaction_graph(evs) == {"Lead": {"Opus": 1}}


class TestInteractionRankings:
    def test_out_and_in_degree(self):
        # Alice<->Bob exchange, plus Carol replies to Alice -> Alice received 2.
        evs = a.normalize_events(
            [
                _ev("Alice", "#best", "AGENT_TALK", "2026-06-02T17:00:00Z"),
                _ev("Bob", "#best", "AGENT_TALK", "2026-06-02T17:01:00Z"),
                _ev("Alice", "#best", "AGENT_TALK", "2026-06-02T17:02:00Z"),
                _ev("Carol", "#best", "AGENT_TALK", "2026-06-02T17:03:00Z"),
            ]
        )
        ranks = a.interaction_rankings(evs)
        # Each of the three made exactly one reply -> tie broken by name.
        assert ranks["top_responders"] == [
            {"agent": "Alice", "count": 1},
            {"agent": "Bob", "count": 1},
            {"agent": "Carol", "count": 1},
        ]
        # Alice was replied to by both Bob and Carol -> 2; Bob once.
        assert ranks["top_targets"] == [
            {"agent": "Alice", "count": 2},
            {"agent": "Bob", "count": 1},
        ]

    def test_count_desc_then_name(self):
        # Bob replies to Alice three times; Alice replies to Bob once.
        evs = a.normalize_events(
            [
                _ev("Alice", "#best", "AGENT_TALK", "2026-06-02T17:00:00Z"),
                _ev("Bob", "#best", "AGENT_TALK", "2026-06-02T17:01:00Z"),
                _ev("Alice", "#best", "AGENT_TALK", "2026-06-02T17:02:00Z"),
                _ev("Bob", "#best", "AGENT_TALK", "2026-06-02T17:03:00Z"),
                _ev("Alice", "#best", "AGENT_TALK", "2026-06-02T17:04:00Z"),
                _ev("Bob", "#best", "AGENT_TALK", "2026-06-02T17:05:00Z"),
            ]
        )
        ranks = a.interaction_rankings(evs)
        assert ranks["top_responders"] == [
            {"agent": "Bob", "count": 3},
            {"agent": "Alice", "count": 2},
        ]
        assert ranks["top_targets"] == [
            {"agent": "Alice", "count": 3},
            {"agent": "Bob", "count": 2},
        ]

    def test_empty(self):
        assert a.interaction_rankings([]) == {
            "top_responders": [],
            "top_targets": [],
        }

    def test_matches_graph_totals(self):
        # Rankings must equal the row/column sums of interaction_graph.
        evs = a.normalize_events(
            [
                _ev("Lead", "#best", "AGENT_TALK", "2026-06-02T17:00:00Z"),
                _ev("Opus", "#best", "AGENT_TALK", "2026-06-02T17:01:00Z"),
                _ev("Lead", "#general", "AGENT_TALK", "2026-06-02T17:02:00Z"),
                _ev("Gem", "#general", "AGENT_TALK", "2026-06-02T17:03:00Z"),
            ]
        )
        graph = a.interaction_graph(evs)
        ranks = a.interaction_rankings(evs)
        out = {row["agent"]: row["count"] for row in ranks["top_responders"]}
        expected_out = {r: sum(t.values()) for r, t in graph.items()}
        assert out == expected_out
