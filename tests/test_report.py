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
    }


def test_render_includes_core_dashboard_sections():
    html = render(sample_metrics(), {"room": "#best", "days": 1, "version": "0.1.0"})

    assert "Village Pulse Dashboard" in html
    assert "Agent activity" in html
    assert "Room participation" in html
    assert "GPT-5.5" in html
    assert "Kimi K2.6" in html
    assert "#best" in html
    assert "Raw metrics payload" in html


def test_generate_writes_parent_directories(tmp_path):
    output = tmp_path / "nested" / "pulse.html"

    resolved = generate(sample_metrics(), output, {"agent": "GPT-5.5"})

    assert resolved == output.resolve()
    assert output.exists()
    assert "GPT-5.5" in output.read_text(encoding="utf-8")
