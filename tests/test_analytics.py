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
        {"userName": "admin", "roomId": "#best", "actionType": "USER_TALK",
         "createdAt": "2026-06-01T11:00:00Z", "content": "note"},
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


@pytest.mark.parametrize("value,expected_year", [
    ("2026-06-01T09:00:00Z", 2026),
    ("2026-06-01T09:00:00+00:00", 2026),
    ("2026-06-01 09:00:00", 2026),
    (1700000000, 2023),          # epoch seconds
    (1700000000000, 2023),       # epoch milliseconds
    (datetime(2026, 6, 1, tzinfo=timezone.utc), 2026),
])
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


def test_messages_per_agent_counts_all_when_not_message_only(sample_raw):
    result = a.messages_per_agent(
        a.normalize_events(sample_raw), message_only=False
    )
    assert result["Alice"] == 3  # includes the PAUSE


def test_messages_per_agent_per_day(sample_raw):
    result = a.messages_per_agent_per_day(a.normalize_events(sample_raw))
    assert result["Bob"] == {"2026-05-31": 1, "2026-06-01": 1}
    assert result["Alice"] == {"2026-06-01": 2}


def test_messages_per_day_is_sorted(sample_raw):
    result = a.messages_per_day(a.normalize_events(sample_raw))
    assert list(result.keys()) == ["2026-05-31", "2026-06-01"]
    assert result["2026-06-01"] == 4  # Alice x2, Bob x1, admin x1


def test_action_type_breakdown(sample_raw):
    result = a.action_type_breakdown(a.normalize_events(sample_raw))
    assert result["AGENT_TALK"] == 4
    assert result["PAUSE"] == 1
    assert result["USER_TALK"] == 1


def test_room_participation(sample_raw):
    result = a.room_participation(a.normalize_events(sample_raw))
    assert result["#best"]["Alice"] == 2
    assert result["#rest"] == {"Bob": 1}


def test_room_participation_rates_sum_to_one(sample_raw):
    rates = a.room_participation_rates(a.normalize_events(sample_raw))
    for room, agents in rates.items():
        assert abs(sum(agents.values()) - 1.0) < 1e-6, room


def test_busiest_hours_zero_filled(sample_raw):
    hours = a.busiest_hours(a.normalize_events(sample_raw))
    assert len(hours) == 24
    assert hours[9] == 2  # 09:00 and 09:15
    assert hours[11] == 1
    assert hours[0] == 0


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
        "meta", "messages_per_agent", "messages_per_agent_per_day",
        "messages_per_day", "action_type_breakdown", "room_participation",
        "room_participation_rates", "busiest_hours", "busiest_weekdays",
        "agent_last_seen", "active_agents", "room_health", "token_usage",
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
    assert list(result.keys()) == ["Alice", "Bob"]  # Carol has no tokens; sorted by total
    assert result["Alice"] == {"input": 400, "output": 30, "total": 430,
                               "efficiency": round(400 / 30, 2)}
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
