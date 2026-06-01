"""Tests for the Village Pulse HTML report generator."""

from village_pulse.report import generate, render


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
    assert "Peak 1,300" in html
    assert "Daily trends" in html
    assert "2026-05-29" in html
    assert "2026-06-01" in html
    assert "Token usage" in html
    assert "Total tokens" in html
    assert "1,300" in html
    assert "12.5:1" in html
    assert "Raw metrics payload" in html


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
    assert "Daily trends" in html
    assert "No daily trend metrics were provided." in html


def test_render_handles_missing_token_usage():
    metrics = sample_metrics()
    metrics.pop("token_usage")

    html = render(metrics, {})

    assert "Token usage" in html
    assert "No token usage metrics were provided." in html
