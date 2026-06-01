"""Tests for village_pulse.archive_compare module."""

import village_pulse.archive_compare as archive_compare

from village_pulse.archive_compare import (
    _bar_svg,
    _build_agent_leaderboard,
    _build_comparison_table,
    _build_daily_trends_table,
    _build_room_activity_trends,
    _build_room_participation,
    _build_summary_cards,
    _build_top_agent_trends,
    _format_number,
    _sparkline_svg,
    generate_comparison,
)


class TestSparklineSVG:
    def test_empty_values(self):
        svg = _sparkline_svg([])
        assert "no data" in svg
        assert "svg" in svg

    def test_single_value(self):
        svg = _sparkline_svg([42])
        assert "polyline" in svg
        assert "circle" in svg

    def test_multi_value(self):
        svg = _sparkline_svg([10, 20, 15, 30])
        assert "polyline" in svg
        assert "circle" in svg
        assert "2f6fed" in svg  # brand color

    def test_all_zeros(self):
        svg = _sparkline_svg([0, 0, 0])
        assert "no data" in svg


class TestBarSVG:
    def test_empty_values(self):
        svg = _bar_svg([], [])
        assert "no data" in svg

    def test_single_bar(self):
        svg = _bar_svg([10], ["best"])
        assert "rect" in svg
        assert "best" in svg

    def test_multi_bar(self):
        svg = _bar_svg([10, 20, 5], ["best", "rest", "general"])
        assert svg.count("rect") == 3
        assert "best" in svg
        assert "rest" in svg


class TestFormatNumber:
    def test_int(self):
        assert _format_number(1234) == "1,234"

    def test_float(self):
        assert _format_number(1234.5) == "1,234.5"

    def test_zero(self):
        assert _format_number(0) == "0"


class TestBuildSummaryCards:
    def test_empty(self):
        html = _build_summary_cards([])
        assert "Total Messages" in html
        assert "0" in html

    def test_with_data(self):
        metrics = [
            {"messages": 100, "events": 50, "agents": 5},
            {"messages": 200, "events": 80, "agents": 7},
        ]
        html = _build_summary_cards(metrics)
        assert "Total Messages" in html
        assert "200" in html  # latest value
        assert "polyline" in html


class TestBuildComparisonTable:
    def test_empty(self):
        html = _build_comparison_table([])
        assert "Day" in html
        assert "Messages" in html

    def test_with_data(self):
        metrics = [
            {"day": 420, "messages": 100, "events": 50, "agents": 5, "tokens": 1000, "efficiency": 85.5},
            {"day": 421, "messages": 200, "events": 80, "agents": 7, "tokens": 2000, "efficiency": 90.0},
        ]
        html = _build_comparison_table(metrics)
        assert "Day 420" in html
        assert "Day 421" in html
        assert "100" in html
        assert "85.5%" in html

    def test_escapes_day_label(self):
        metrics = [
            {
                "day": '<script>alert("day")</script>',
                "messages": 1,
                "events": 1,
                "agents": 1,
                "tokens": 0,
                "efficiency": None,
            }
        ]
        html = _build_comparison_table(metrics)
        assert "<script" not in html
        assert "</script>" not in html
        assert "&lt;script&gt;" in html
        assert "&quot;day&quot;" in html


class TestBuildAgentLeaderboard:
    def test_empty(self):
        html = _build_agent_leaderboard([])
        assert "No agent data" in html

    def test_with_data(self):
        metrics = [
            {
                "top_agents": [
                    {"agent": "Alice", "messages": 100},
                    {"agent": "Bob", "messages": 50},
                ]
            }
        ]
        html = _build_agent_leaderboard(metrics)
        assert "Alice" in html
        assert "Bob" in html
        assert "100" in html
        assert "rect" in html  # bar chart


class TestBuildRoomParticipation:
    def test_empty_days(self):
        html = _build_room_participation([])
        assert "No room data" in html

    def test_with_data(self):
        metrics = [
            {"room_participation": {"best": 100, "rest": 50}}
        ]
        html = _build_room_participation(metrics)
        assert "best" in html
        assert "rest" in html
        assert "rect" in html


class TestBuildDailyTrendsTable:
    def test_empty(self):
        html = _build_daily_trends_table([])
        assert "No daily trend data" in html

    def test_with_data(self):
        metrics = [
            {
                "daily_trends": [
                    {"date": "2026-05-30", "messages": 100, "events": 50, "active_agents": 5, "total_tokens": 1000, "efficiency": 85.5},
                    {"date": "2026-05-31", "messages": 200, "events": 80, "active_agents": 7, "total_tokens": 2000, "efficiency": 90.0},
                ]
            }
        ]
        html = _build_daily_trends_table(metrics)
        assert "2026-05-30" in html
        assert "2026-05-31" in html
        assert "100" in html
        assert "85.5%" in html



class TestBuildTopAgentTrends:
    def test_empty_days(self):
        html = _build_top_agent_trends([])
        assert "No agent activity data" in html

    def test_rows_without_dates_do_not_render_misleading_trends(self):
        html = _build_top_agent_trends([
            {"top_agents": [{"agent": "Alice", "messages": 3}]}
        ])
        assert "No agent activity data" in html
        assert "Alice" not in html

    def test_sorts_by_total_messages_and_applies_top_n(self):
        html = _build_top_agent_trends(
            [
                {
                    "daily_trends": [{"date": "2026-06-01"}],
                    "top_agents": [
                        {"agent": "Alice", "messages": 3},
                        {"agent": "Bob", "messages": 5},
                        {"agent": "Carol", "messages": 1},
                    ],
                }
            ],
            top_n=2,
        )
        assert html.find("Bob") < html.find("Alice")
        assert "Carol" not in html
        assert html.count("<svg") == 2

    def test_escapes_agent_names(self):
        html = _build_top_agent_trends([
            {
                "daily_trends": [{"date": "2026-06-01"}],
                "top_agents": [{"agent": '<img src=x onerror="alert(1)">', "messages": 3}],
            }
        ])
        assert "<img" not in html
        assert "&lt;img" in html
        assert "onerror=&quot;alert(1)&quot;" in html

    def test_aligns_sparse_agents_on_shared_date_axis(self, monkeypatch):
        captured = []

        def fake_sparkline(values):
            captured.append(values)
            return "<svg></svg>"

        monkeypatch.setattr(archive_compare, "_sparkline_svg", fake_sparkline)
        html = _build_top_agent_trends([
            {
                "daily_trends": [{"date": "2026-06-01"}],
                "top_agents": [{"agent": "Alice", "messages": 3}],
            },
            {
                "daily_trends": [{"date": "2026-06-02"}],
                "top_agents": [{"agent": "Bob", "messages": 5}],
            },
        ])

        assert html.find("Bob") < html.find("Alice")
        assert captured == [[0, 5], [3, 0]]


class TestBuildRoomActivityTrends:
    def test_empty_days(self):
        html = _build_room_activity_trends([])
        assert "No room activity data" in html

    def test_rows_without_dates_do_not_render_misleading_trends(self):
        html = _build_room_activity_trends([
            {"room_participation": {"best": {"Alice": 3}}}
        ])
        assert "No room activity data" in html
        assert "best" not in html

    def test_accepts_nested_and_numeric_room_counts(self):
        html = _build_room_activity_trends([
            {
                "daily_trends": [{"date": "2026-06-01"}],
                "room_participation": {"best": {"Alice": 3}, "rest": 2},
            }
        ])
        assert "best" in html
        assert "rest" in html
        assert '<td class="num">3</td>' in html
        assert '<td class="num">2</td>' in html
        assert html.count("<svg") == 2

    def test_escapes_room_names(self):
        html = _build_room_activity_trends([
            {
                "daily_trends": [{"date": "2026-06-01"}],
                "room_participation": {'<script>alert("room")</script>': {"Alice": 3}},
            }
        ])
        assert "<script" not in html
        assert "&lt;script&gt;" in html
        assert "&quot;room&quot;" in html

    def test_aligns_sparse_rooms_on_shared_date_axis(self, monkeypatch):
        captured = []

        def fake_sparkline(values):
            captured.append(values)
            return "<svg></svg>"

        monkeypatch.setattr(archive_compare, "_sparkline_svg", fake_sparkline)
        html = _build_room_activity_trends([
            {
                "daily_trends": [{"date": "2026-06-01"}],
                "room_participation": {"best": {"Alice": 3}},
            },
            {
                "daily_trends": [{"date": "2026-06-02"}],
                "room_participation": {"rest": {"Bob": 5}},
            },
        ])

        assert html.find("rest") < html.find("best")
        assert captured == [[0, 5], [3, 0]]


class TestGenerateComparison:
    def test_generates_html_file(self, tmp_path):
        day_metrics = [
            {
                "day": 420,
                "messages": 100,
                "events": 50,
                "agents": 5,
                "tokens": 1000,
                "efficiency": 85.5,
                "room_participation": {"best": 80, "rest": 20},
                "top_agents": [{"agent": "Alice", "messages": 50}],
                "daily_trends": [
                    {"date": "2026-05-30", "messages": 100, "events": 50, "active_agents": 5, "total_tokens": 1000, "efficiency": 85.5},
                ],
            }
        ]
        output = tmp_path / "comparison.html"
        generate_comparison(day_metrics, output, village_day=426)

        assert output.exists()
        html = output.read_text()
        assert "Village Pulse" in html
        assert "Multi-Day Comparison" in html
        assert "Day 420" in html
        assert "Alice" in html
        assert "Summary" in html
        assert "Agent Leaderboard" in html
        assert "Room Participation" in html
        assert "Daily Trends" in html
        assert "Top Agents Over Time" in html
        assert "Room Activity Over Time" in html

    def test_places_new_trend_sections_after_daily_trends(self, tmp_path):
        output = tmp_path / "comparison.html"
        generate_comparison([], output, village_day=426)

        html = output.read_text()
        daily = html.find("<h2>Daily Trends (Last 7 Days)</h2>")
        agents = html.find("<h2>Top Agents Over Time</h2>")
        rooms = html.find("<h2>Room Activity Over Time</h2>")
        assert -1 not in {daily, agents, rooms}
        assert daily < agents < rooms

    def test_escapes_village_day_header(self, tmp_path):
        output = tmp_path / "comparison.html"
        generate_comparison([], output, village_day='<img src=x onerror="alert(1)">')

        html = output.read_text()
        assert "<img" not in html
        assert "&lt;img" in html
        assert "onerror=&quot;alert(1)&quot;" in html

class TestGenerateComparisonArchiveOrchestration:
    def test_skips_error_and_empty_days_and_writes_dashboard(self, tmp_path, monkeypatch):
        clients = []

        class FakeClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                clients.append(self)

            def _discover_latest_day(self):
                return None

            def iter_raw_events_for_day(self, day):
                if day == 1:
                    raise archive_compare.api_client.APIError("temporary outage")
                if day == 2:
                    return iter([])
                return iter([
                    {
                        "id": "event-3",
                        "createdAt": "2026-06-01T17:00:00Z",
                        "data": {
                            "agentId": "agent-1",
                            "roomId": "room-1",
                            "actionType": "AGENT_TALK",
                            "content": "hello",
                            "inputTokens": 12,
                            "outputTokens": 3,
                        },
                    }
                ])

            def get_agents(self):
                return {"agent-1": "Alice"}

            def get_rooms(self):
                return {"room-1": "best"}

        rendered = []

        def fake_generate_comparison(day_metrics, output_path, village_day=0):
            rendered.append((day_metrics, output_path, village_day))
            output_path.write_text("comparison", encoding="utf-8")

        monkeypatch.setattr(archive_compare.api_client, "VillageAPIClient", FakeClient)
        monkeypatch.setattr(archive_compare, "generate_comparison", fake_generate_comparison)

        output = archive_compare.generate_comparison_archive(
            tmp_path,
            days_back=3,
            endpoint="https://example.invalid/api/",
            village_slug="custom-slug",
            village_id="village-1",
        )

        assert output == tmp_path / "comparison.html"
        assert output.read_text(encoding="utf-8") == "comparison"
        assert [c.kwargs for c in clients] == [
            {
                "village_slug": "custom-slug",
                "endpoint": "https://example.invalid/api/",
                "village_id": "village-1",
            }
        ]
        assert len(rendered) == 1
        day_metrics, output_path, village_day = rendered[0]
        assert output_path == output
        assert village_day == 3
        assert [d["day"] for d in day_metrics] == [3]
        assert day_metrics[0]["messages"] == 1
        assert day_metrics[0]["events"] == 1
        assert day_metrics[0]["agents"] == 1
        assert day_metrics[0]["tokens"] == 15
        assert day_metrics[0]["efficiency"] == 4.0
        assert day_metrics[0]["room_participation"] == {"best": {"Alice": 1}}
        assert day_metrics[0]["top_agents"] == [{"agent": "Alice", "messages": 1}]
        assert day_metrics[0]["daily_trends"][0]["date"] == "2026-06-01"


class TestArchiveCompareCLI:
    def test_main_forwards_options_and_prints_output(self, tmp_path, monkeypatch, capsys):
        calls = []
        expected = tmp_path / "comparison.html"

        def fake_generate_comparison_archive(**kwargs):
            calls.append(kwargs)
            return expected

        monkeypatch.setattr(
            archive_compare,
            "generate_comparison_archive",
            fake_generate_comparison_archive,
        )

        rc = archive_compare.main([
            "--output",
            str(tmp_path),
            "--days-back",
            "9",
            "--endpoint",
            "https://example.invalid/api/",
        ])

        assert rc == 0
        assert calls == [
            {
                "output_dir": str(tmp_path),
                "days_back": 9,
                "endpoint": "https://example.invalid/api/",
            }
        ]
        assert f"Comparison dashboard written to: {expected}" in capsys.readouterr().out

    def test_main_returns_one_when_generation_fails(self, tmp_path, monkeypatch):
        def boom(**_kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(archive_compare, "generate_comparison_archive", boom)

        rc = archive_compare.main(["--output", str(tmp_path)])

        assert rc == 1



# Additions by Gemini 3.5 Flash to maximize coverage

class TestArchiveCompareCoverageEdges:
    def test_vmax_zero(self):
        svg = _bar_svg([-1, 0], ["best", "rest"])
        assert "rect" in svg
        assert "best" in svg

    def test_empty_room_participation_keys(self):
        html = _build_room_participation([{"room_participation": {}}])
        assert "No room data" in html

    def test_daily_trends_duplicate_and_limit(self):
        metrics = [
            {
                "daily_trends": [
                    {"date": "2026-05-22", "messages": 10, "events": 5, "active_agents": 2, "total_tokens": 100, "efficiency": 50.0},
                    {"date": "2026-05-23", "messages": 10, "events": 5, "active_agents": 2, "total_tokens": 100, "efficiency": 50.0},
                    {"date": "2026-05-24", "messages": 10, "events": 5, "active_agents": 2, "total_tokens": 100, "efficiency": 50.0},
                    {"date": "2026-05-25", "messages": 10, "events": 5, "active_agents": 2, "total_tokens": 100, "efficiency": 50.0},
                    {"date": "2026-05-26", "messages": 10, "events": 5, "active_agents": 2, "total_tokens": 100, "efficiency": 50.0},
                    {"date": "2026-05-27", "messages": 10, "events": 5, "active_agents": 2, "total_tokens": 100, "efficiency": 50.0},
                    {"date": "2026-05-28", "messages": 10, "events": 5, "active_agents": 2, "total_tokens": 100, "efficiency": 50.0},
                    {"date": "2026-05-28", "messages": 10, "events": 5, "active_agents": 2, "total_tokens": 100, "efficiency": 50.0},  # duplicate
                ]
            }
        ]
        html = _build_daily_trends_table(metrics)
        assert "2026-05-28" in html
        assert html.count("<tr>") <= 8  # header + max 7 unique rows


class TestGenerateComparisonArchiveGenerator:
    def test_generate_comparison_archive_success(self, tmp_path, monkeypatch):
        from village_pulse import archive_compare

        class FakeClient:
            def __init__(self, **kwargs):
                pass
            def _discover_latest_day(self):
                return 5
            def iter_raw_events_for_day(self, day):
                if day == 5:
                    return [
                        {
                            "id": "event_1",
                            "eventIndex": 1,
                            "createdAt": "2026-06-01T10:00:00Z",
                            "data": {
                                "actionType": "AGENT_TALK",
                                "agentName": "Alice",
                                "roomId": "room_1",
                                "content": "hello",
                                "inputTokens": 10,
                                "outputTokens": 20
                            }
                        }
                    ]
                return []
            def get_agents(self):
                return {"agent_1": "Alice"}
            def get_rooms(self):
                return {"room_1": "best"}

        monkeypatch.setattr(archive_compare.api_client, "VillageAPIClient", FakeClient)

        out_dir = tmp_path / "output"
        res_path = archive_compare.generate_comparison_archive(
            output_dir=out_dir,
            days_back=2,
            village_slug="test-slug"
        )
        assert res_path.exists()
        assert (out_dir / "comparison.html").exists()

    def test_generate_comparison_archive_no_latest_day(self, tmp_path, monkeypatch):
        from village_pulse import archive_compare

        class FakeClient:
            def __init__(self, **kwargs):
                pass
            def _discover_latest_day(self):
                return None
            def iter_raw_events_for_day(self, day):
                return []
            def get_agents(self):
                return {}
            def get_rooms(self):
                return {}

        monkeypatch.setattr(archive_compare.api_client, "VillageAPIClient", FakeClient)

        out_dir = tmp_path / "output_no_day"
        res_path = archive_compare.generate_comparison_archive(
            output_dir=out_dir,
            days_back=2,
            village_slug="test-slug"
        )
        assert res_path.exists()
