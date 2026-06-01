"""Tests for the village_pulse CLI entry point."""

import json

import subprocess
import sys
from pathlib import Path


from village_pulse import __version__
from village_pulse.__main__ import _build_parser


class TestParser:
    def test_defaults(self):
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.output == Path("report.html")
        assert args.days == 7
        assert args.room is None
        assert args.agent is None
        assert args.endpoint == "https://theaidigest.org/village/api/"
        assert args.verbose is False

    def test_custom_args(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["--output", "/tmp/out.html", "--room", "#best", "--days", "3", "--agent", "Kimi", "--verbose"]
        )
        assert args.output == Path("/tmp/out.html")
        assert args.room == "#best"
        assert args.days == 3
        assert args.agent == "Kimi"
        assert args.verbose is True


class TestMainImports:
    def test_main_returns_error_when_modules_missing(self, monkeypatch):
        """If api_client/analytics/report are missing, main should return 1."""
        # Clear and reload __main__ so the in-function import resolves fresh,
        # then set the submodules to ``None`` (which makes ``import`` raise
        # ImportError). We must do this AFTER clearing, otherwise the cleanup
        # loop would wipe our blocking markers.
        for mod in list(sys.modules):
            if mod.startswith("village_pulse"):
                del sys.modules[mod]
        monkeypatch.setitem(sys.modules, "village_pulse.api_client", None)
        monkeypatch.setitem(sys.modules, "village_pulse.analytics", None)
        monkeypatch.setitem(sys.modules, "village_pulse.report", None)

        import village_pulse.__main__ as vm

        result = vm.main(["--output", "/tmp/test_report.html"])
        assert result == 1


class TestVersion:
    def test_version_string(self):
        assert __version__ == "0.1.0"

    def test_cli_version_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "village_pulse", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "0.1.0" in result.stdout


class TestHelp:
    def test_cli_help_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "village_pulse", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Real-time village activity monitoring" in result.stdout


class TestFormatJson:
    def test_json_output_writes_metrics(self, tmp_path, monkeypatch):
        """--format json writes analytics metrics as JSON, skipping HTML report."""
        fake_metrics = {
            "meta": {"total_events": 2, "total_messages": 2},
            "messages_per_agent": {"Kimi K2.6": 2},
            "action_type_breakdown": {"AGENT_TALK": 2},
        }

        def fake_fetch(**kwargs):
            return [
                {"agent_name": "Kimi K2.6", "room": "best", "action_type": "AGENT_TALK", "content": "hi"},
            ]

        import village_pulse.api_client as ac
        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an
        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        import village_pulse.report as rp
        generate_calls = []
        monkeypatch.setattr(rp, "generate", lambda **kwargs: generate_calls.append(kwargs))

        from village_pulse.__main__ import main

        out = tmp_path / "metrics.json"
        rc = main(["--format", "json", "--output", str(out)])

        assert rc == 0
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["meta"]["total_events"] == 2
        assert data["messages_per_agent"]["Kimi K2.6"] == 2
        # HTML report should NOT have been generated.
        assert generate_calls == []

    def test_html_output_still_calls_report_generate(self, tmp_path, monkeypatch):
        """Default --format html still invokes report.generate."""
        fake_metrics = {"meta": {"total_events": 1}}

        def fake_fetch(**kwargs):
            return [{"agent_name": "X", "room": "best", "action_type": "AGENT_TALK", "content": "y"}]

        import village_pulse.api_client as ac
        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an
        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        import village_pulse.report as rp
        generate_calls = []
        monkeypatch.setattr(rp, "generate", lambda **kwargs: generate_calls.append(kwargs) or out)

        from village_pulse.__main__ import main

        out = tmp_path / "report.html"
        rc = main(["--output", str(out)])

        assert rc == 0
        assert len(generate_calls) == 1
        assert generate_calls[0]["metrics"] == fake_metrics


class TestMetricsFlag:
    def test_metrics_flag_filters_json_output(self, tmp_path, monkeypatch):
        """--metrics messages,active_agents filters compute_all result."""
        fake_metrics = {
            "meta": {"total_events": 2},
            "messages_per_agent": {"A": 2},
            "active_agents": ["A"],
            "room_health": {"best": 1.0},
        }

        def fake_fetch(**kwargs):
            return [{"agent_name": "A", "room": "best", "action_type": "AGENT_TALK", "content": "x"}]

        import village_pulse.api_client as ac
        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an
        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        from village_pulse.__main__ import main

        out = tmp_path / "filtered.json"
        rc = main(["--format", "json", "--metrics", "messages_per_agent,active_agents", "--output", str(out)])

        assert rc == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "meta" in data
        assert "messages_per_agent" in data
        assert "active_agents" in data
        assert "room_health" not in data

    def test_metrics_all_includes_everything(self, tmp_path, monkeypatch):
        """Default --metrics all keeps every key."""
        fake_metrics = {
            "meta": {"total_events": 1},
            "messages_per_agent": {"A": 1},
            "room_health": {"best": 1.0},
        }

        def fake_fetch(**kwargs):
            return [{"agent_name": "A", "room": "best", "action_type": "AGENT_TALK", "content": "x"}]

        import village_pulse.api_client as ac
        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an
        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        from village_pulse.__main__ import main

        out = tmp_path / "all.json"
        rc = main(["--format", "json", "--output", str(out)])

        assert rc == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert set(data.keys()) == {"meta", "messages_per_agent", "room_health"}
