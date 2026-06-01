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
        "daily_trends", "agent_daily_trends", "top_agents_over_time",
        "room_daily_trends",
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
    assert alice[0] == {"date": "2026-06-01", "messages": 1,
                        "input_tokens": 100, "output_tokens": 10}
    assert alice[1] == {"date": "2026-06-02", "messages": 1,
                        "input_tokens": 300, "output_tokens": 20}
    # Bob only appears on one day; Carol has no tokens but is still a message.
    bob = a.agent_daily_trends(events, "Bob")
    assert bob == [{"date": "2026-06-01", "messages": 1,
                    "input_tokens": 50, "output_tokens": 25}]
    carol = a.agent_daily_trends(events, "Carol")
    assert carol == [{"date": "2026-06-01", "messages": 1,
                      "input_tokens": 0, "output_tokens": 0}]
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
        "date": "2026-06-01", "events": 2, "messages": 2,
        "active_agents": 2, "input_tokens": 100, "output_tokens": 10,
    }
    assert best[1] == {
        "date": "2026-06-02", "events": 1, "messages": 1,
        "active_agents": 1, "input_tokens": 300, "output_tokens": 20,
    }
    rest = a.room_daily_trends(events, "#rest")
    assert rest == [{
        "date": "2026-06-01", "events": 1, "messages": 1,
        "active_agents": 1, "input_tokens": 50, "output_tokens": 25,
    }]
    assert a.room_daily_trends(events, "#nowhere") == []
    assert a.room_daily_trends([], "#best") == []
    # wired into compute_all for all rooms, empty -> {}
    summary = a.compute_all(token_raw)
    assert summary["room_daily_trends"]["#best"] == best
    assert a.compute_all([])["room_daily_trends"] == {}


def test_agent_trends_in_compute_all(token_raw):
    summary = a.compute_all(token_raw)
    assert summary["agent_daily_trends"]["Alice"] == \
        a.agent_daily_trends(a.normalize_events(token_raw), "Alice")
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
    out = a.densify([{"date": "2026-05-26", "messages": 7}], axis, ["messages", "events"])
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
