"""Tests for village_pulse.archive.

These tests exercise the archive generator with mocked API data so they can
run offline and quickly.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


from village_pulse import archive


def _make_raw_event(event_index: int, action_type: str = "AGENT_TALK", agent_name: str = "TestAgent", room: str = "best") -> dict:
    return {
        "id": f"ev-{event_index}",
        "eventIndex": event_index,
        "createdAt": "2026-06-01T10:00:00.000Z",
        "data": {
            "actionType": action_type,
            "agentName": agent_name,
            "roomId": "room-1",
            "content": f"message {event_index}",
            "inputTokens": 100,
            "outputTokens": 10,
        },
    }


class TestGenerateArchive:
    def test_generates_reports_and_index(self, tmp_path: Path) -> None:
        """Archive produces one report per day plus an index page."""
        mock_client = MagicMock()
        mock_client._discover_latest_day.return_value = 426
        mock_client.get_agents.return_value = {"room-1": "TestAgent"}
        mock_client.get_rooms.return_value = {"room-1": "best"}
        mock_client.iter_raw_events_for_day.side_effect = lambda day: [
            _make_raw_event(1, agent_name="Alice"),
            _make_raw_event(2, agent_name="Bob"),
        ]

        with patch("village_pulse.archive.api_client.VillageAPIClient", return_value=mock_client):
            reports = archive.generate_archive(tmp_path, days_back=3)

        assert len(reports) == 3
        for r in reports:
            day = r["day"]
            report_path = tmp_path / f"report_day{day}.html"
            assert report_path.exists()
            assert r["total_events"] == 2
            assert r["total_messages"] == 2
            assert r["unique_agents"] == 2

        index_path = tmp_path / "index.html"
        assert index_path.exists()
        index_html = index_path.read_text(encoding="utf-8")
        assert "Village Pulse Archive" in index_html
        assert "report_day426.html" in index_html
        assert "report_day425.html" in index_html
        assert "report_day424.html" in index_html
        assert 'href="report_latest.html">Latest report</a>' in index_html

    def test_skips_empty_days(self, tmp_path: Path) -> None:
        """Days with no events are silently skipped."""
        mock_client = MagicMock()
        mock_client._discover_latest_day.return_value = 426
        mock_client.get_agents.return_value = {}
        mock_client.get_rooms.return_value = {}
        mock_client.iter_raw_events_for_day.side_effect = lambda day: [] if day == 425 else [_make_raw_event(1)]

        with patch("village_pulse.archive.api_client.VillageAPIClient", return_value=mock_client):
            reports = archive.generate_archive(tmp_path, days_back=3)

        days = {r["day"] for r in reports}
        assert 426 in days
        assert 425 not in days
        assert 424 in days

    def test_api_error_skips_day(self, tmp_path: Path) -> None:
        """An APIError for a single day should not crash the whole archive."""
        from village_pulse.api_client import APIError

        mock_client = MagicMock()
        mock_client._discover_latest_day.return_value = 426
        mock_client.get_agents.return_value = {}
        mock_client.get_rooms.return_value = {}

        def _side_effect(day: int) -> list[dict]:
            if day == 425:
                raise APIError("simulated failure", status=500)
            return [_make_raw_event(1)]

        mock_client.iter_raw_events_for_day.side_effect = _side_effect

        with patch("village_pulse.archive.api_client.VillageAPIClient", return_value=mock_client):
            reports = archive.generate_archive(tmp_path, days_back=3)

        days = {r["day"] for r in reports}
        assert 426 in days
        assert 425 not in days
        assert 424 in days


    def test_latest_report_uses_newest_non_empty_day(self, tmp_path: Path) -> None:
        """report_latest.html should point at the newest day that produced a report."""
        mock_client = MagicMock()
        mock_client._discover_latest_day.return_value = 426
        mock_client.get_agents.return_value = {"room-1": "Alice"}
        mock_client.get_rooms.return_value = {"room-1": "best"}

        def _side_effect(day: int) -> list[dict]:
            if day == 426:
                return []
            return [_make_raw_event(day, agent_name=f"Agent{day}")]

        mock_client.iter_raw_events_for_day.side_effect = _side_effect

        with patch("village_pulse.archive.api_client.VillageAPIClient", return_value=mock_client):
            reports = archive.generate_archive(tmp_path, days_back=3)

        assert [r["day"] for r in reports] == [425, 424]
        assert not (tmp_path / "report_day426.html").exists()
        assert (tmp_path / "report_latest.html").read_text(encoding="utf-8") == (tmp_path / "report_day425.html").read_text(encoding="utf-8")
        index_html = (tmp_path / "index.html").read_text(encoding="utf-8")
        assert 'href="report_latest.html">Latest report</a>' in index_html
        assert "report_day425.html" in index_html
        assert "report_day426.html" not in index_html


class TestGenerateIndexPage:
    def test_index_has_days_sorted_newest_first(self, tmp_path: Path) -> None:
        reports = [
            {"day": 3, "filename": "report_day3.html", "total_events": 10, "total_messages": 5, "unique_agents": 2},
            {"day": 2, "filename": "report_day2.html", "total_events": 0, "total_messages": 0, "unique_agents": 0},
            {"day": 1, "filename": "report_day1.html", "total_events": 20, "total_messages": 15, "unique_agents": 3},
        ]
        archive._generate_index_page(reports, tmp_path, generated_at="2026-06-01 10:00 UTC", village_day=3)

        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        # Newest first in table body
        pos3 = html.find("Day 3")
        pos1 = html.find("Day 1")
        pos2 = html.find("Day 2")
        assert pos3 < pos2
        assert pos2 < pos1

    def test_index_omits_latest_link_when_no_reports(self, tmp_path: Path) -> None:
        archive._generate_index_page([], tmp_path, generated_at="2026-06-01 10:00 UTC", village_day=426)

        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        assert "Village Pulse Archive" in html
        assert "report_latest.html" not in html
        assert "Latest report" not in html


    def test_index_can_link_comparison_dashboard(self, tmp_path: Path) -> None:
        reports = [
            {"day": 426, "filename": "report_day426.html", "total_events": 10, "total_messages": 5, "unique_agents": 2},
        ]

        archive._generate_index_page(
            reports,
            tmp_path,
            generated_at="2026-06-01 10:00 UTC",
            village_day=426,
            comparison_filename="comparison.html",
        )

        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        assert 'href="report_latest.html">Latest report</a>' in html
        assert 'href="comparison.html">Comparison dashboard</a>' in html


    def test_index_can_link_comparison_dashboard_without_reports(self, tmp_path: Path) -> None:
        archive._generate_index_page(
            [],
            tmp_path,
            generated_at="2026-06-01 10:00 UTC",
            village_day=426,
            comparison_filename="comparison.html",
        )

        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        assert 'href="comparison.html">Comparison dashboard</a>' in html
        assert "report_latest.html" not in html
        assert "Latest report" not in html


    def test_index_escapes_comparison_dashboard_filename(self, tmp_path: Path) -> None:
        archive._generate_index_page(
            [],
            tmp_path,
            generated_at="2026-06-01 10:00 UTC",
            village_day=426,
            comparison_filename='comparison.html" onclick="alert(1)',
        )

        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        assert 'onclick="alert(1)' not in html
        assert 'href="comparison.html&quot; onclick=&quot;alert(1)">Comparison dashboard</a>' in html


    def test_index_escapes_report_filename_and_metadata(self, tmp_path: Path) -> None:
        reports = [
            {
                "day": '<script>alert("day")</script>',
                "filename": 'report_day426.html" onclick="alert(1)',
                "total_events": '<script>alert("events")</script>',
                "total_messages": 5,
                "unique_agents": '<script>alert("agents")</script>',
            },
        ]

        archive._generate_index_page(
            reports,
            tmp_path,
            generated_at='<script>alert("time")</script>',
            village_day='<script>alert("village")</script>',
        )

        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        assert '<script>alert' not in html
        assert 'onclick="alert(1)' not in html
        assert 'href="report_day426.html&quot; onclick=&quot;alert(1)">Day &lt;script&gt;alert(&quot;day&quot;)&lt;/script&gt;</a>' in html
        assert '&lt;script&gt;alert(&quot;events&quot;)&lt;/script&gt;' in html
        assert '&lt;script&gt;alert(&quot;agents&quot;)&lt;/script&gt;' in html
        assert 'Current village day: &lt;script&gt;alert(&quot;village&quot;)&lt;/script&gt;' in html
        assert 'Generated &lt;script&gt;alert(&quot;time&quot;)&lt;/script&gt;' in html


class TestCLI:
    def test_main_with_mocked_archive(self, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client._discover_latest_day.return_value = 426
        mock_client.get_agents.return_value = {}
        mock_client.get_rooms.return_value = {}
        mock_client.iter_raw_events_for_day.return_value = [_make_raw_event(1)]

        with patch("village_pulse.archive.api_client.VillageAPIClient", return_value=mock_client):
            rc = archive.main(["--output", str(tmp_path), "--days-back", "2"])

        assert rc == 0
        assert (tmp_path / "index.html").exists()
        assert (tmp_path / "report_day426.html").exists()

    def test_main_failure_returns_nonzero(self, tmp_path: Path) -> None:
        from village_pulse.api_client import APIError

        mock_client = MagicMock()
        mock_client._discover_latest_day.side_effect = APIError("boom", status=500)

        with patch("village_pulse.archive.api_client.VillageAPIClient", return_value=mock_client):
            rc = archive.main(["--output", str(tmp_path), "--days-back", "2"])

        assert rc == 1
