"""Tests for the Village Pulse HTML report generator."""

from village_pulse.report import (
    generate,
    render,
    _agent_daily_rows,
    _agent_status_lists,
    _agent_trend_charts,
    _daily_trend_values,
    _first_number,
    _hour_rows,
    _looks_numeric,
    _mapping,
    _room_rows,
    _string_list,
    _token_rows,
    _token_summary,
    _trend_charts,
    _interaction_graph_rows,
    _interaction_rankings,
    _response_latency_rows,
)


def sample_metrics():
    return {
        "meta": {"total_messages": 3, "unique_agents": 2, "unique_rooms": 1},
        "messages_per_agent": {"GPT-5.5": 2, "Kimi K2.6": 1},
        "messages_per_day": {"2026-06-01": 3},
        "room_participation": {"#best": {"GPT-5.5": 2, "Kimi K2.6": 1}},
        "busiest_hours": {"17": 2, "18": 1},
        "active_agents": {"active": ["GPT-5.5"], "inactive": ["Kimi K2.6"]},
        "daily_trends": [
            {
                "date": "2026-05-29",
                "events": 2,
                "messages": 1,
                "active_agents": 1,
                "input_tokens": 300,
                "output_tokens": 30,
                "total_tokens": 330,
                "efficiency": 10,
            },
            {
                "date": "2026-06-01",
                "events": 4,
                "messages": 3,
                "active_agents": 2,
                "input_tokens": 1200,
                "output_tokens": 100,
                "total_tokens": 1300,
                "efficiency": 12,
            },
        ],
        "top_agents_over_time": [
            {
                "agent": "GPT-5.5",
                "total_messages": 3,
                "daily": [
                    {
                        "date": "2026-05-29",
                        "messages": 1,
                        "input_tokens": 300,
                        "output_tokens": 30,
                    },
                    {
                        "date": "2026-06-01",
                        "messages": 2,
                        "input_tokens": 1000,
                        "output_tokens": 80,
                    },
                ],
            }
        ],
        "token_usage": {
            "totals": {
                "input": 1200,
                "output": 100,
                "total": 1300,
                "efficiency": 12,
                "events_with_tokens": 2,
            },
            "per_agent": {
                "GPT-5.5": {
                    "input": 1000,
                    "output": 80,
                    "total": 1080,
                    "efficiency": 12.5,
                },
                "Kimi K2.6": {
                    "input": 200,
                    "output": 20,
                    "total": 220,
                    "efficiency": 10,
                },
            },
            "per_room": {
                "#best": {"input": 1200, "output": 100, "total": 1300, "efficiency": 12}
            },
        },
    }


def test_render_includes_core_dashboard_sections():
    html = render(sample_metrics(), {"room": "#best", "days": 1, "version": "0.1.0"})

    assert "Village Pulse Dashboard" in html
    assert "Agent activity" in html
    assert "Room participation" in html
    assert "GPT-5.5" in html
    assert "Kimi K2.6" in html
    assert "#best" in html
    assert "Trends over time" in html
    assert "Messages over time" in html
    assert "Tokens over time" in html
    assert "Active agents over time" in html
    assert '<svg class="sparkline"' in html
    assert "Messages over time trend" in html
    assert "Daily messages over time values from 2026-05-29 to 2026-06-01 with a peak of 3." in html
    assert "Peak 1,300" in html
    assert "Top agent trends" in html
    assert "GPT-5.5 message trend" in html
    assert "with a peak of 2 messages and 1,410 tokens" in html
    assert "3 messages" in html
    assert "1,410 tokens" in html
    assert "Daily trends" in html
    assert "2026-05-29" in html
    assert "2026-06-01" in html
    assert "Token usage" in html
    assert "Total tokens" in html
    assert "1,300" in html
    assert "12.5:1" in html
    assert "Raw metrics payload" in html


def test_render_escapes_agent_names_in_trend_svg_metadata():
    metrics = sample_metrics()
    metrics["messages_per_agent"] = {'<script>alert("x")</script>': 1}
    metrics["top_agents_over_time"] = [
        {
            "agent": '<script>alert("x")</script>',
            "total_messages": 1,
            "daily": [
                {
                    "date": "2026-06-01",
                    "messages": 1,
                    "input_tokens": 5,
                    "output_tokens": 1,
                }
            ],
        }
    ]

    html = render(metrics, {})

    assert '<script>alert("x")</script>' not in html
    assert '&lt;script&gt;alert(&#34;x&#34;)&lt;/script&gt; message trend' in html
    assert (
        'Daily message counts for &lt;script&gt;alert(&#34;x&#34;)&lt;/script&gt; from 2026-06-01'
        in html
    )


def test_generate_writes_parent_directories(tmp_path):
    output = tmp_path / "nested" / "pulse.html"

    resolved = generate(sample_metrics(), output, {"agent": "GPT-5.5"})

    assert resolved == output.resolve()
    assert output.exists()
    assert "GPT-5.5" in output.read_text(encoding="utf-8")


def test_render_handles_missing_daily_trends():
    metrics = sample_metrics()
    metrics.pop("daily_trends")

    html = render(metrics, {})

    assert "Trends over time" in html
    assert "No trend chart metrics were provided." in html
    assert "Top agent trends" in html
    assert "Daily trends" in html
    assert "No daily trend metrics were provided." in html


def test_render_handles_missing_top_agent_trends():
    metrics = sample_metrics()
    metrics.pop("top_agents_over_time")

    html = render(metrics, {})

    assert "Top agent trends" in html
    assert "No per-agent trend metrics were provided." in html


def test_render_handles_explicit_empty_trend_series():
    metrics = sample_metrics()
    metrics["daily_trends"] = []
    metrics["top_agents_over_time"] = []

    html = render(metrics, {})

    assert "Trends over time" in html
    assert "No trend chart metrics were provided." in html
    assert "Top agent trends" in html
    assert "No per-agent trend metrics were provided." in html
    assert "Daily trends" in html
    assert "No daily trend metrics were provided." in html
    assert '<svg class="sparkline"' not in html


def test_render_handles_missing_token_usage():
    metrics = sample_metrics()
    metrics.pop("token_usage")

    html = render(metrics, {})

    assert "Token usage" in html
    assert "No token usage metrics were provided." in html

def test_daily_trend_values_skips_non_mapping_and_missing_date():
    values = [
        {"date": "2026-01-01", "messages": 1},
        "not-a-mapping",
        {"messages": 2},
    ]
    rows = _daily_trend_values(values)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-01-01"


def test_trend_charts_returns_empty_for_empty_rows():
    assert _trend_charts([]) == []


def test_agent_trend_charts_respects_limit_and_skips_invalid():
    values = [
        "not-a-mapping",
        {"agent": "A", "daily": []},
        {"agent": "", "daily": [{"date": "2026-01-01", "messages": 1}]},
        {"no_agent": True, "daily": [{"date": "2026-01-01", "messages": 1}]},
        {"agent": "B", "daily": "string"},
        {"agent": "C", "daily": [{"date": "2026-01-01", "messages": 1}]},
        {"agent": "D", "daily": [{"date": "2026-01-02", "messages": 2}]},
        {"agent": "E", "daily": [{"date": "2026-01-03", "messages": 3}]},
    ]
    charts = _agent_trend_charts(values, limit=2)
    assert len(charts) == 2
    assert charts[0]["agent"] == "C"
    assert charts[1]["agent"] == "D"


def test_agent_daily_rows_skips_missing_date():
    values = [
        {"date": "2026-01-01", "messages": 1},
        {"messages": 2},
    ]
    rows = _agent_daily_rows(values)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-01-01"


def test_token_summary_returns_empty_for_non_mapping():
    assert _token_summary("not-a-mapping", {}) == []


def test_token_rows_skips_non_mapping_value():
    values = {
        "agent1": {"input": 100, "output": 10},
        "agent2": "not-a-mapping",
    }
    rows = _token_rows(values)
    assert len(rows) == 1
    assert rows[0]["name"] == "agent1"


def test_first_number_returns_len_for_sequence():
    metrics = {"agents": ["a", "b", "c"]}
    assert _first_number(metrics, "agents", "total") == 3


def test_first_number_returns_safe_int_for_non_sequence():
    metrics = {"total_messages": 42}
    assert _first_number(metrics, "total_messages") == 42


def test_mapping_returns_empty_dict_when_no_match():
    assert _mapping({"foo": "bar"}, "baz", "qux") == {}


def test_room_rows_handles_flat_numeric_and_agents_fallbacks():
    room_metrics = {
        "#best": {"messages": 5, "agents": ["a", "b"]},
        "#rest": 10,
        "#general": {"participation": "high"},
    }
    rows = _room_rows(room_metrics)
    by_room = {row["room"]: row for row in rows}
    assert by_room["#best"]["messages"] == 5
    assert by_room["#best"]["agents"] == 2
    assert by_room["#rest"]["messages"] == 10
    assert by_room["#rest"]["agents"] == "—"
    assert by_room["#general"]["agents"] == 0


def test_hour_rows_handles_various_inputs():
    # Mapping input
    mapping_result = _hour_rows({"17": 2, "18": 1})
    assert len(mapping_result) == 2
    assert mapping_result[0] == {"hour": "17", "count": 2}

    # Sequence of mappings
    seq_mapping = _hour_rows([{"hour": "17", "count": 2}, {"hour": "18", "messages": 1}])
    assert len(seq_mapping) == 2
    assert seq_mapping[0] == {"hour": "17", "count": 2}

    # Sequence of tuples
    seq_tuple = _hour_rows([("17", 2), ("18", 1)])
    assert len(seq_tuple) == 2
    assert seq_tuple[0] == {"hour": "17", "count": 2}

    # Non-mapping, non-sequence
    assert _hour_rows(42) == []


def test_agent_status_lists_and_string_list():
    active, inactive = _agent_status_lists(None, None)
    assert active == []
    assert inactive == []

    assert _string_list(None) == []
    assert _string_list({"a": 1, "b": 2}) == ["a", "b"]
    assert _string_list("single") == ["single"]


def test_looks_numeric_false_for_invalid():
    assert _looks_numeric("abc") is False
    assert _looks_numeric(None) is False


def test_render_fallback_total_messages_from_agent_counts():
    metrics = {
        "meta": {},
        "messages_per_agent": {"A": 5, "B": 3},
        "messages_per_day": {},
        "room_participation": {},
        "busiest_hours": {},
        "active_agents": {},
        "daily_trends": [],
        "top_agents_over_time": [],
        "token_usage": {},
    }
    html = render(metrics, {})
    assert "8" in html  # 5 + 3 total messages


def test_interaction_graph_rows_edge_cases():
    # Non-mapping
    assert _interaction_graph_rows(None) == []
    assert _interaction_graph_rows("not-a-mapping") == []

    # Valid mapping but with invalid/empty targets to hit line 903
    graph = {
        "Opus": None,               # hits targets is not a Mapping -> continue
        "Kimi": {},                 # hits not targets -> continue
        "GPT": {"Lead": 3},         # valid
    }
    rows = _interaction_graph_rows(graph)
    assert len(rows) == 1
    assert rows[0]["responder"] == "GPT"
    assert rows[0]["targets"] == [{"name": "Lead", "count": 3, "percent": 100.0}]


def test_interaction_rankings_edge_cases():
    # Non-mapping
    assert _interaction_rankings(None) == {"top_responders": [], "top_targets": []}
    assert _interaction_rankings("not-a-mapping") == {"top_responders": [], "top_targets": []}

    # Empty list or non-mapping elements in rankings lists
    rankings = {
        "top_responders": [None, "invalid", {"agent": "Opus", "count": 5}],
        "top_targets": [None, "invalid", {"agent": "Kimi", "count": 3}],
    }
    res = _interaction_rankings(rankings)
    assert len(res["top_responders"]) == 1
    assert res["top_responders"][0] == {"agent": "Opus", "count": 5}
    assert len(res["top_targets"]) == 1
    assert res["top_targets"][0] == {"agent": "Kimi", "count": 3}


def test_render_includes_response_speed_section_and_escapes_agents():
    metrics = sample_metrics()
    metrics["response_latency"] = [
        {"agent": "Fast Agent", "median_seconds": 12.3, "responses": 4},
        {"agent": "<b>Slow</b>", "median_seconds": 45.0, "responses": 2},
    ]

    html = render(metrics, {"days": 7})

    assert "Response speed (7-Day Digest)" in html
    assert "Median response" in html
    assert "Fast Agent" in html
    assert "12.3s" in html
    assert "4" in html
    assert "&lt;b&gt;Slow&lt;/b&gt;" in html
    assert "<b>Slow</b>" not in html


def test_response_latency_rows_filters_invalid_and_limits():
    values = [
        None,
        "invalid",
        {"agent": "A", "median_seconds": 10.5, "responses": "3"},
        {"median_seconds": 20, "responses": 2},
        {"agent": "B", "median_seconds": 30, "responses": None},
    ]

    rows = _response_latency_rows(values, limit=1)

    assert rows == [{"agent": "A", "median_seconds": 10.5, "responses": 3}]


def test_render_response_speed_empty_state():
    metrics = sample_metrics()
    metrics["response_latency"] = []

    html = render(metrics, {})

    assert "Response speed" in html
    assert "No agent-to-agent responses detected in the window." in html


def test_render_digest_mode():
    metrics = sample_metrics()
    html = render(metrics, {"room": "#best", "days": 7, "version": "0.1.0"})
    assert "Village Pulse - 7-Day Digest" in html
    assert "Agent activity (7-Day Digest)" in html
    assert "Activity digest trend (7 days)" in html
    assert "Daily sparkline" in html
