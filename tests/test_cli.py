"""Tests for the village_pulse CLI entry point."""

import json

import subprocess
import sys
from pathlib import Path


from village_pulse import __version__
from village_pulse.__main__ import _build_parser, _filter_metrics, _selected_metric_keys


class TestParser:
    def test_defaults(self):
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.output is None
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
            "daily_trends": [{"date": "2026-06-01", "messages": 2}],
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



    def test_json_stdout_when_no_output_flag(self, monkeypatch, capsys):
        """--format json without -o prints JSON to stdout."""
        fake_metrics = {
            "meta": {"total_events": 1},
            "messages_per_agent": {"A": 1},
        }

        def fake_fetch(**kwargs):
            return [{"agent_name": "A", "room": "best", "action_type": "AGENT_TALK", "content": "x"}]

        import village_pulse.api_client as ac
        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an
        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        import village_pulse.report as rp
        generate_calls = []
        monkeypatch.setattr(rp, "generate", lambda **kwargs: generate_calls.append(kwargs))

        from village_pulse.__main__ import main

        rc = main(["--format", "json"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["meta"]["total_events"] == 1
        assert generate_calls == []

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


class TestMetricsAliases:
    def test_selected_metric_keys_expands_friendly_aliases(self):
        keys = _selected_metric_keys("messages,tokens")

        assert keys is not None
        assert "meta" in keys
        assert "messages_per_agent" in keys
        assert "messages_per_agent_per_day" in keys
        assert "messages_per_day" in keys
        assert "token_usage" in keys

    def test_selected_metric_keys_keeps_exact_metric_names(self):
        keys = _selected_metric_keys("messages_per_agent,active_agents")

        assert keys == {"meta", "messages_per_agent", "active_agents"}


    def test_activity_alias_includes_daily_trends(self):
        filtered = _filter_metrics(
            {
                "meta": {"total_events": 2},
                "daily_trends": [{"date": "2026-06-01", "messages": 2}],
                "agent_daily_trends": {"GPT-5.5": [{"date": "2026-06-01", "messages": 2}]},
                "top_agents_over_time": [
                    {"agent": "GPT-5.5", "total_messages": 2, "daily": []}
                ],
                "room_daily_trends": {"best": [{"date": "2026-06-01", "messages": 2}]},
                "active_agents": {"active": ["GPT-5.5"], "inactive": []},
                "messages_per_agent": {"GPT-5.5": 2},
            },
            "activity",
        )

        assert "meta" in filtered
        assert "daily_trends" in filtered
        assert "agent_daily_trends" in filtered
        assert "top_agents_over_time" in filtered
        assert "room_daily_trends" in filtered
        assert "active_agents" in filtered
        assert "messages_per_agent" not in filtered

    def test_metrics_aliases_filter_json_output(self, tmp_path, monkeypatch):
        """--metrics messages,tokens expands aliases before filtering."""
        fake_metrics = {
            "meta": {"total_events": 2},
            "messages_per_agent": {"A": 2},
            "messages_per_day": {"2026-06-01": 2},
            "token_usage": {"totals": {"input": 100, "output": 10, "total": 110, "efficiency": 10}},
            "room_health": {"best": 1.0},
        }

        def fake_fetch(**kwargs):
            return [{"agent_name": "A", "room": "best", "action_type": "AGENT_TALK", "content": "x"}]

        import village_pulse.api_client as ac
        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an
        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        from village_pulse.__main__ import main

        out = tmp_path / "alias-filtered.json"
        rc = main(["--format", "json", "--metrics", "messages,tokens", "--output", str(out)])

        assert rc == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "meta" in data
        assert "messages_per_agent" in data
        assert "messages_per_day" in data
        assert "token_usage" in data
        assert "room_health" not in data


class TestFormatCsv:
    def test_csv_output_writes_file(self, tmp_path, monkeypatch):
        """--format csv writes flat events as CSV."""
        fake_events = [
            {
                "created_at": "2026-06-01T10:00:00Z",
                "agent_name": "Kimi K2.6",
                "room": "best",
                "action_type": "AGENT_TALK",
                "content": "hello",
                "input_tokens": 100,
                "output_tokens": 20,
            },
            {
                "created_at": "2026-06-01T11:00:00Z",
                "agent_name": "GPT-5.5",
                "room": "rest",
                "action_type": "AGENT_TALK",
                "content": "world",
                "input_tokens": 200,
                "output_tokens": None,
            },
        ]

        import village_pulse.api_client as ac
        monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: fake_events)

        import village_pulse.analytics as an
        monkeypatch.setattr(an, "compute_all", lambda _events: {"meta": {}})

        from village_pulse.__main__ import main

        out = tmp_path / "events.csv"
        rc = main(["--format", "csv", "--output", str(out)])

        assert rc == 0
        assert out.exists()
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        assert lines[0] == "timestamp,agent,room,action_type,content,input_tokens,output_tokens"
        assert "Kimi K2.6" in lines[1]
        assert "GPT-5.5" in lines[2]
        assert lines[1].endswith(",100,20")
        assert lines[2].endswith(",200,")

    def test_csv_stdout_when_no_output_flag(self, monkeypatch, capsys):
        """--format csv without -o prints CSV to stdout."""
        fake_events = [
            {
                "created_at": "2026-06-01T10:00:00Z",
                "agent_name": "A",
                "room": "best",
                "action_type": "AGENT_TALK",
                "content": "hi",
                "input_tokens": 10,
                "output_tokens": 5,
            },
        ]

        import village_pulse.api_client as ac
        monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: fake_events)

        import village_pulse.analytics as an
        monkeypatch.setattr(an, "compute_all", lambda _events: {"meta": {}})

        from village_pulse.__main__ import main

        rc = main(["--format", "csv"])
        assert rc == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "timestamp,agent,room,action_type,content,input_tokens,output_tokens"
        assert lines[1].endswith(",10,5")


    def test_csv_escapes_commas_and_newlines(self, tmp_path, monkeypatch):
        """CSV writer must quote cells containing commas or newlines."""
        fake_events = [
            {
                "created_at": "2026-06-01T10:00:00Z",
                "agent_name": "A",
                "room": "best",
                "action_type": "AGENT_TALK",
                "content": "Hello, world!\nSecond line",
                "input_tokens": 10,
                "output_tokens": 5,
            },
        ]

        import village_pulse.api_client as ac
        monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: fake_events)

        import village_pulse.analytics as an
        monkeypatch.setattr(an, "compute_all", lambda _events: {"meta": {}})

        from village_pulse.__main__ import main

        out = tmp_path / "edge.csv"
        rc = main(["--format", "csv", "--output", str(out)])
        assert rc == 0
        text = out.read_text(encoding="utf-8")
        # The content cell should be quoted because it contains a comma and newline
        assert '"Hello, world!\nSecond line"' in text
