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
    _heatmap_cells,
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

    assert "Village Pulse — #best" in html
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
    assert (
        "Daily messages over time values from 2026-05-29 to 2026-06-01 with a peak of 3."
        in html
    )
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
    assert "&lt;script&gt;alert(&#34;x&#34;)&lt;/script&gt; message trend" in html
    assert (
        "Daily message counts for &lt;script&gt;alert(&#34;x&#34;)&lt;/script&gt; from 2026-06-01"
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
    seq_mapping = _hour_rows(
        [{"hour": "17", "count": 2}, {"hour": "18", "messages": 1}]
    )
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
        "Opus": None,  # hits targets is not a Mapping -> continue
        "Kimi": {},  # hits not targets -> continue
        "GPT": {"Lead": 3},  # valid
    }
    rows = _interaction_graph_rows(graph)
    assert len(rows) == 1
    assert rows[0]["responder"] == "GPT"
    assert rows[0]["targets"] == [{"name": "Lead", "count": 3, "percent": 100.0}]


def test_interaction_rankings_edge_cases():
    # Non-mapping
    assert _interaction_rankings(None) == {"top_responders": [], "top_targets": []}
    assert _interaction_rankings("not-a-mapping") == {
        "top_responders": [],
        "top_targets": [],
    }

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
    assert "Village Pulse - 7-Day Digest — #best" in html


def test_render_digest_mode_no_room():
    metrics = sample_metrics()
    html = render(metrics, {"days": 7, "version": "0.1.0"})
    assert "Village Pulse - 7-Day Digest" in html
    assert "Agent activity (7-Day Digest)" in html
    assert "Activity digest trend (7 days)" in html
    assert "Daily sparkline" in html


def test_heatmap_cells_accepts_mapping_and_truncates_long_sequences():
    from village_pulse.report import _heatmap_cells

    mapped = _heatmap_cells({"0": 1, "23": "4", "24": 9})
    assert len(mapped) == 24
    assert mapped[0]["count"] == 1
    assert mapped[23]["count"] == 4
    assert all(cell["hour"] != 24 for cell in mapped)

    long_sequence = _heatmap_cells(list(range(30)))
    assert len(long_sequence) == 24
    assert long_sequence[23]["count"] == 23


def test_room_title_formatting_variations():
    # 1. Room with hash prefix already, with day
    html1 = render(sample_metrics(), {"room": "#best", "day": 427, "version": "0.1.0"})
    assert "Village Pulse — Day 427 — #best" in html1

    # 2. Room without hash prefix, with day (should auto-prefix with #)
    html2 = render(sample_metrics(), {"room": "best", "day": 427, "version": "0.1.0"})
    assert "Village Pulse — Day 427 — #best" in html2

    # 3. Room with hash prefix, no day
    html3 = render(sample_metrics(), {"room": "#best", "version": "0.1.0"})
    assert "Village Pulse — #best" in html3

    # 4. Room without hash prefix, no day (should auto-prefix with #)
    html4 = render(sample_metrics(), {"room": "best", "version": "0.1.0"})
    assert "Village Pulse — #best" in html4


def test_heatmap_cells_edge_cases():
    # 1. Mapping input
    mapping_res = _heatmap_cells({"5": 10, "-1": 5, "24": 5})
    assert len(mapping_res) == 24
    assert mapping_res[5]["count"] == 10
    assert mapping_res[5]["level"] == 4
    assert mapping_res[0]["count"] == 0

    # 2. Sequence longer than 24
    seq_res = _heatmap_cells([1] * 26)
    assert len(seq_res) == 24
    for i in range(24):
        assert seq_res[i]["count"] == 1

    # 3. Invalid input type (string)
    assert _heatmap_cells("invalid_type") == []


def test_conversation_depth_view_edge_cases():
    from village_pulse.report import _conversation_depth_view

    # 1. Non-mapping input
    res1 = _conversation_depth_view("not_a_mapping")
    assert res1["total_chains"] == 0
    assert res1["max_depth"] == 0
    assert res1["mean_depth"] == 0.0
    assert res1["median_depth"] == 0.0
    assert res1["distribution_rows"] == []

    # 2. Non-numeric or missing numeric inputs
    res2 = _conversation_depth_view(
        {
            "total_chains": "invalid",
            "max_depth": None,
            "mean_depth": "abc",
            "median_depth": "def",
        }
    )
    assert res2["total_chains"] == 0
    assert res2["max_depth"] == 0
    assert res2["mean_depth"] == 0.0
    assert res2["median_depth"] == 0.0

    # 3. Invalid or malformed depth_distribution
    res3 = _conversation_depth_view({"depth_distribution": "not_a_mapping"})
    assert res3["distribution_rows"] == []

    # 4. depth_distribution with invalid/non-numeric keys or values
    res4 = _conversation_depth_view(
        {
            "depth_distribution": {
                "invalid_key": 5,
                "2": "invalid_val",
                "3": 10,
                "4": -5,
            }
        }
    )
    assert len(res4["distribution_rows"]) == 1
    assert res4["distribution_rows"][0]["depth"] == 3
    assert res4["distribution_rows"][0]["count"] == 10
    assert res4["distribution_rows"][0]["percent"] == 100.0


def test_render_includes_conversation_depth():
    from village_pulse.report import render

    metrics = sample_metrics()
    metrics["conversation_depth"] = {
        "total_chains": 12,
        "max_depth": 5,
        "mean_depth": 3.4,
        "median_depth": 3.0,
        "depth_distribution": {
            "2": 8,
            "3": 3,
            "5": 1,
        },
    }
    html = render(metrics, {"version": "0.1.0"})
    assert "Conversation depth" in html
    assert "Total chains" in html
    assert "12" in html
    assert "Max depth (longest chain)" in html
    assert "5" in html
    assert "Mean depth" in html
    assert "3.4" in html
    assert "Median depth" in html
    assert "3.0" in html
    assert "Depth 2" in html
    assert "Depth 3" in html
    assert "Depth 5" in html


def test_chain_initiators_view_edge_cases():
    from village_pulse.report import _chain_initiators_view

    # 1. Non-list inputs
    assert _chain_initiators_view(None) == []
    assert _chain_initiators_view("not_a_list") == []
    assert _chain_initiators_view({}) == []

    # 2. List with non-mapping, non-tuple elements
    assert _chain_initiators_view([123, "string"]) == []

    # 3. Mappings with missing or invalid keys
    res = _chain_initiators_view(
        [
            {"agent": 123, "chains": 5},  # agent is not str
            {"agent": "Alice", "chains": "invalid"},  # chains is not int
            {"agent": "Bob", "chains": -1},  # chains <= 0
            {"agent": "Charlie"},  # chains missing
        ]
    )
    assert res == []

    # 4. Valid sorting and percentage computation, and HTML-escaping
    res2 = _chain_initiators_view(
        [
            {"agent": "Bob", "chains": 5},
            {"agent": "Alice", "chains": 10},
            {"agent": "<script>Eve</script>", "chains": 5},
        ]
    )
    assert len(res2) == 3
    assert res2[0] == {"agent": "Alice", "chains": 10, "percent": 50.0}
    assert res2[1] == {
        "agent": "&lt;script&gt;Eve&lt;/script&gt;",
        "chains": 5,
        "percent": 25.0,
    }
    assert res2[2] == {"agent": "Bob", "chains": 5, "percent": 25.0}

    # 5. Tuple inputs of length 2
    res3 = _chain_initiators_view(
        [
            (123, 5),  # agent is not str (uncovered line)
            ("Alice", 10),
            ("Bob", 5),
        ]
    )
    assert len(res3) == 2
    assert res3[0] == {"agent": "Alice", "chains": 10, "percent": 2 / 3 * 100}
    assert res3[1] == {"agent": "Bob", "chains": 5, "percent": 1 / 3 * 100}


def test_render_includes_chain_initiators():
    from village_pulse.report import render

    metrics = sample_metrics()
    metrics["conversation_depth"] = {
        "total_chains": 15,
        "max_depth": 5,
        "mean_depth": 3.4,
        "median_depth": 3.0,
        "depth_distribution": {"2": 15},
    }
    metrics["chain_initiators"] = [
        {"agent": "Alice", "chains": 10},
        {"agent": "Bob", "chains": 5},
    ]
    html = render(metrics, {"version": "0.1.0"})
    assert "Chain initiators" in html
    assert "Alice" in html
    assert "10" in html
    assert "Bob" in html
    assert "5" in html


def test_top_interaction_pairs_view_edge_cases():
    from village_pulse.report import _top_interaction_pairs_view

    # 1. Non-list/tuple input
    assert _top_interaction_pairs_view(None) == []
    assert _top_interaction_pairs_view("not-a-list") == []

    # 2. Empty input
    assert _top_interaction_pairs_view([]) == []

    # 3. Invalid rows (not Mapping, missing count/pair, invalid pair format)
    assert (
        _top_interaction_pairs_view(
            [
                "not-a-mapping",
                {"count": 5},  # missing pair
                {"pair": ["Alice"]},  # pair too short
                {"pair": "not-a-list", "count": 5},  # pair not list/tuple
            ]
        )
        == []
    )

    # 4. Correct coercion, percentage computation, and stable input ordering
    res = _top_interaction_pairs_view(
        [
            {"pair": ["Bob", "Alice"], "count": 10},
            {"pair": ["<script>Eve</script>", "Dave"], "count": 5},
        ]
    )
    assert len(res) == 2
    assert res[0]["pair"] == ["Bob", "Alice"]
    assert res[0]["pair_str"] == "Bob ↔ Alice"
    assert res[0]["count"] == 10
    assert res[0]["percent"] == 100.0

    assert res[1]["pair"] == ["<script>Eve</script>", "Dave"]
    assert res[1]["pair_str"] == "<script>Eve</script> ↔ Dave"
    assert res[1]["count"] == 5
    assert res[1]["percent"] == 50.0

    # 5. Limit truncation
    many_rows = [{"pair": ["Alice", "Bob"], "count": i} for i in range(20)]
    assert len(_top_interaction_pairs_view(many_rows, limit=5)) == 5


def test_render_includes_top_interaction_pairs():
    from village_pulse.report import render

    metrics = sample_metrics()
    metrics["top_interaction_pairs"] = [
        {"pair": ["Alice", "Bob"], "count": 12},
    ]
    html = render(metrics, {"version": "0.1.0"})
    assert "Strongest partnerships" in html
    assert "Alice ↔ Bob" in html
    assert "12" in html


def test_render_top_interaction_pairs_escapes_once():
    from village_pulse.report import render

    metrics = sample_metrics()
    metrics["top_interaction_pairs"] = [
        {"pair": ["<script>Eve</script>", "Bob & Co"], "count": 7},
    ]

    rendered = render(metrics, {"version": "0.1.0"})
    assert "<script>Eve</script>" not in rendered
    assert "&lt;script&gt;Eve&lt;/script&gt; ↔ Bob &amp; Co" in rendered
    assert "&amp;lt;script" not in rendered
    assert "Bob &amp;amp; Co" not in rendered


def test_weekday_rows_edge_cases():
    from village_pulse.report import _weekday_rows

    # 1. Non-mapping, non-sequence inputs
    assert _weekday_rows(None) == []
    assert _weekday_rows(123) == []
    assert _weekday_rows("string") == []

    # 2. Mapping input
    mapping_val = {"Tuesday": 5, "Monday": 10, "Sunday": 1}
    res = _weekday_rows(mapping_val)
    assert len(res) == 3
    assert res[0] == {"weekday": "Monday", "count": 10}
    assert res[1] == {"weekday": "Tuesday", "count": 5}
    assert res[2] == {"weekday": "Sunday", "count": 1}

    # 3. Sequence of Mapping inputs
    seq_mapping = [
        {"weekday": "Friday", "count": 2},
        {"day": "Wednesday", "messages": 4},
    ]
    res_seq = _weekday_rows(seq_mapping)
    assert len(res_seq) == 2
    assert res_seq[0] == {"weekday": "Wednesday", "count": 4}
    assert res_seq[1] == {"weekday": "Friday", "count": 2}

    # 4. Sequence of Sequences
    seq_seq = [["Thursday", 8], ["Monday", 12]]
    res_seq_seq = _weekday_rows(seq_seq)
    assert len(res_seq_seq) == 2
    assert res_seq_seq[0] == {"weekday": "Monday", "count": 12}
    assert res_seq_seq[1] == {"weekday": "Thursday", "count": 8}


def test_render_includes_busiest_weekdays():
    from village_pulse.report import render

    # Test when data is present
    metrics = sample_metrics()
    metrics["busiest_weekdays"] = {"Monday": 10, "Wednesday": 5}
    html = render(metrics, {"version": "0.1.0"})
    assert "Busiest weekdays" in html
    assert "Monday" in html
    assert "10" in html
    assert "Wednesday" in html
    assert "5" in html

    # Test fallback path when no weekday metrics are provided
    metrics_empty = sample_metrics()
    if "busiest_weekdays" in metrics_empty:
        del metrics_empty["busiest_weekdays"]
    if "messages_by_weekday" in metrics_empty:
        del metrics_empty["messages_by_weekday"]
    html_empty = render(metrics_empty, {"version": "0.1.0"})
    assert "Busiest weekdays" in html_empty
    assert "No weekday activity metrics were provided." in html_empty



def test_action_type_rows_edge_cases():
    from village_pulse.report import _action_type_rows

    # 1. Non-mapping, non-sequence inputs
    assert _action_type_rows(None) == []
    assert _action_type_rows(123) == []
    assert _action_type_rows("string") == []

    # 2. Mapping input (counts descending, alphabetical sorting for ties)
    mapping_val = {"key": 5, "hold_key": 10, "type": 10}
    res = _action_type_rows(mapping_val)
    assert len(res) == 3
    assert res[0] == {"type": "hold_key", "count": 10}
    assert res[1] == {"type": "type", "count": 10}
    assert res[2] == {"type": "key", "count": 5}

    # 3. Sequence of Mapping inputs
    seq_mapping = [
        {"type": "screenshot", "count": 2},
        {"action_type": "left_click", "events": 4},
        {"action_type": None},
    ]
    res_seq = _action_type_rows(seq_mapping)
    assert len(res_seq) == 3
    assert res_seq[0] == {"type": "left_click", "count": 4}
    assert res_seq[1] == {"type": "screenshot", "count": 2}
    assert res_seq[2] == {"type": "—", "count": 0}

    # 4. Sequence of Sequences
    seq_seq = [["key", 8], ["type", 12]]
    res_seq_seq = _action_type_rows(seq_seq)
    assert len(res_seq_seq) == 2
    assert res_seq_seq[0] == {"type": "type", "count": 12}
    assert res_seq_seq[1] == {"type": "key", "count": 8}


def test_render_includes_action_types():
    from village_pulse.report import render

    # Test when data is present
    metrics = sample_metrics()
    metrics["action_type_breakdown"] = {"AGENT_TALK": 10, "CONSOLIDATE": 5}
    html = render(metrics, {"version": "0.1.0"})
    assert "Action types" in html
    assert "AGENT_TALK" in html
    assert "10" in html
    assert "CONSOLIDATE" in html
    assert "5" in html

    # Test fallback path when no action type metrics are provided
    metrics_empty = sample_metrics()
    if "action_type_breakdown" in metrics_empty:
        del metrics_empty["action_type_breakdown"]
    if "action_types" in metrics_empty:
        del metrics_empty["action_types"]
    html_empty = render(metrics_empty, {"version": "0.1.0"})
    assert "Action types" in html_empty
    assert "No action type metrics were provided." in html_empty
