"""Tests for village_pulse.archive_compare module."""



from village_pulse.archive_compare import (
    _bar_svg,
    _build_agent_leaderboard,
    _build_comparison_table,
    _build_daily_trends_table,
    _build_room_participation,
    _build_summary_cards,
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

    def test_escapes_village_day_header(self, tmp_path):
        output = tmp_path / "comparison.html"
        generate_comparison([], output, village_day='<img src=x onerror="alert(1)">')

        html = output.read_text()
        assert "<img" not in html
        assert "&lt;img" in html
        assert "onerror=&quot;alert(1)&quot;" in html

