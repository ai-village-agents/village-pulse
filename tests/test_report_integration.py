"""Integration tests for analytics output rendered by the report module."""

from village_pulse.analytics import compute_all
from village_pulse.report import generate


def test_report_accepts_compute_all_metrics(tmp_path):
    events = [
        {
            "agent_name": "GPT-5.5",
            "room_id": "#best",
            "created_at": "2026-06-01T17:00:00Z",
            "action_type": "AGENT_TALK",
            "content": "report complete",
            "inputTokens": 100,
            "outputTokens": 10,
        },
        {
            "agentName": "Kimi K2.6",
            "roomId": "#best",
            "createdAt": "2026-06-01T18:00:00Z",
            "actionType": "AGENT_TALK",
            "content": "cli ready",
            "inputTokens": 50,
            "outputTokens": 5,
        },
    ]
    metrics = compute_all(events)
    output = tmp_path / "dashboard.html"

    resolved = generate(metrics, output, {"room": "#best", "days": 1, "version": "0.1.0"})

    html = resolved.read_text(encoding="utf-8")
    assert "Village Pulse Dashboard" in html
    assert "GPT-5.5" in html
    assert "Kimi K2.6" in html
    assert "#best" in html
    assert "Daily trends" in html
    assert "2026-06-01" in html
    assert "Token usage" in html
    assert "Total tokens" in html
    assert "165" in html
    assert "10.0:1" in html
    assert "&#34;total_messages&#34;: 2" in html
