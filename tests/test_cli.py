"""Tests for the village_pulse CLI entry point."""

import json

import subprocess
import sys
from pathlib import Path


from village_pulse import __version__
from village_pulse.__main__ import (
    _METRIC_ALIASES,
    _build_parser,
    _filter_metrics,
    _selected_metric_keys,
)


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
            [
                "--output",
                "/tmp/out.html",
                "--room",
                "#best",
                "--days",
                "3",
                "--agent",
                "Kimi",
                "--verbose",
            ]
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

    def test_readme_metrics_row_documents_all_aliases(self):
        readme = Path(__file__).resolve().parents[1] / "README.md"
        text = readme.read_text(encoding="utf-8")
        metrics_rows = [
            line for line in text.splitlines() if line.startswith("| `--metrics` |")
        ]

        assert len(metrics_rows) == 1
        row = metrics_rows[0]
        for alias in sorted(_METRIC_ALIASES):
            assert f"`{alias}`" in row


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
                {
                    "agent_name": "Kimi K2.6",
                    "room": "best",
                    "action_type": "AGENT_TALK",
                    "content": "hi",
                },
            ]

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        import village_pulse.report as rp

        generate_calls = []
        monkeypatch.setattr(
            rp, "generate", lambda **kwargs: generate_calls.append(kwargs)
        )

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
            return [
                {
                    "agent_name": "X",
                    "room": "best",
                    "action_type": "AGENT_TALK",
                    "content": "y",
                }
            ]

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        import village_pulse.report as rp

        generate_calls = []
        monkeypatch.setattr(
            rp, "generate", lambda **kwargs: generate_calls.append(kwargs) or out
        )

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
            return [
                {
                    "agent_name": "A",
                    "room": "best",
                    "action_type": "AGENT_TALK",
                    "content": "x",
                }
            ]

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        import village_pulse.report as rp

        generate_calls = []
        monkeypatch.setattr(
            rp, "generate", lambda **kwargs: generate_calls.append(kwargs)
        )

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
            return [
                {
                    "agent_name": "A",
                    "room": "best",
                    "action_type": "AGENT_TALK",
                    "content": "x",
                }
            ]

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        from village_pulse.__main__ import main

        out = tmp_path / "filtered.json"
        rc = main(
            [
                "--format",
                "json",
                "--metrics",
                "messages_per_agent,active_agents",
                "--output",
                str(out),
            ]
        )

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
            return [
                {
                    "agent_name": "A",
                    "room": "best",
                    "action_type": "AGENT_TALK",
                    "content": "x",
                }
            ]

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


class TestDayFlag:
    def test_day_flag_passed_to_fetch_events(self, tmp_path, monkeypatch):
        """--day should be forwarded as current_day to fetch_events."""
        captured = {}

        def fake_fetch(**kwargs):
            captured["kwargs"] = kwargs
            return [
                {
                    "agent_name": "A",
                    "room": "best",
                    "action_type": "AGENT_TALK",
                    "content": "x",
                }
            ]

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an

        monkeypatch.setattr(
            an, "compute_all", lambda _events: {"meta": {"total_events": 1}}
        )

        import village_pulse.report as rp

        monkeypatch.setattr(rp, "generate", lambda **kwargs: None)

        from village_pulse.__main__ import main

        out = tmp_path / "report.html"
        rc = main(["--day", "423", "--days", "1", "--output", str(out)])

        assert rc == 0
        assert captured["kwargs"]["current_day"] == 423
        assert captured["kwargs"]["days"] == 1


class TestCliValidation:
    def test_days_less_than_one_returns_error(self, capsys):
        from village_pulse.__main__ import main

        rc = main(["--days", "0"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "--days must be >= 1" in captured.err

    def test_day_less_than_one_returns_error(self, capsys):
        from village_pulse.__main__ import main

        rc = main(["--day", "0"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "--day must be >= 1" in captured.err

    def test_negative_days_returns_error(self, capsys):
        from village_pulse.__main__ import main

        rc = main(["--days", "-3"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "--days must be >= 1" in captured.err


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

    def test_interactions_alias_includes_graph_rankings_and_pairs(self):
        keys = _selected_metric_keys("interactions")

        assert keys == {
            "meta",
            "interaction_graph",
            "interaction_rankings",
            "top_interaction_pairs",
        }

    def test_activity_alias_includes_daily_trends(self):
        filtered = _filter_metrics(
            {
                "meta": {"total_events": 2},
                "daily_trends": [{"date": "2026-06-01", "messages": 2}],
                "agent_daily_trends": {
                    "GPT-5.5": [{"date": "2026-06-01", "messages": 2}]
                },
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

    def test_interactions_alias_filters_json_output(self, tmp_path, monkeypatch):
        """--metrics interactions expands to graph, rankings, and top pairs."""
        fake_metrics = {
            "meta": {"total_events": 2},
            "interaction_graph": {"B": {"A": 1}},
            "interaction_rankings": {
                "top_responders": [{"agent": "B", "count": 1}],
                "top_targets": [{"agent": "A", "count": 1}],
            },
            "top_interaction_pairs": [{"pair": ["A", "B"], "count": 1}],
            "messages_per_agent": {"A": 1, "B": 1},
        }

        def fake_fetch(**kwargs):
            return [
                {
                    "agent_name": "A",
                    "room": "best",
                    "action_type": "AGENT_TALK",
                    "content": "x",
                }
            ]

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        from village_pulse.__main__ import main

        out = tmp_path / "interactions.json"
        rc = main(
            ["--format", "json", "--metrics", "interactions", "--output", str(out)]
        )

        assert rc == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert set(data) == {
            "meta",
            "interaction_graph",
            "interaction_rankings",
            "top_interaction_pairs",
        }

    def test_metrics_aliases_filter_json_output(self, tmp_path, monkeypatch):
        """--metrics messages,tokens expands aliases before filtering."""
        fake_metrics = {
            "meta": {"total_events": 2},
            "messages_per_agent": {"A": 2},
            "messages_per_day": {"2026-06-01": 2},
            "token_usage": {
                "totals": {"input": 100, "output": 10, "total": 110, "efficiency": 10}
            },
            "room_health": {"best": 1.0},
        }

        def fake_fetch(**kwargs):
            return [
                {
                    "agent_name": "A",
                    "room": "best",
                    "action_type": "AGENT_TALK",
                    "content": "x",
                }
            ]

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", fake_fetch)

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        from village_pulse.__main__ import main

        out = tmp_path / "alias-filtered.json"
        rc = main(
            ["--format", "json", "--metrics", "messages,tokens", "--output", str(out)]
        )

        assert rc == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "meta" in data
        assert "messages_per_agent" in data
        assert "messages_per_day" in data
        assert "token_usage" in data
        assert "room_health" not in data


class TestFormatMarkdown:
    def test_markdown_output_writes_file(self, tmp_path, monkeypatch):
        """--format markdown writes a readable metrics report."""
        fake_events = [
            {
                "agent_name": "GPT-5.5",
                "room": "best",
                "action_type": "AGENT_TALK",
                "content": "hello",
            }
        ]
        fake_metrics = {
            "meta": {
                "total_events": 3,
                "total_messages": 2,
                "unique_agents": 2,
                "unique_rooms": 1,
            },
            "messages_per_agent": {"GPT-5.5": 2, "Kimi K2.6": 1},
            "room_participation": {"best": {"GPT-5.5": 2, "Kimi K2.6": 1}},
            "daily_trends": [
                {"date": "2026-06-02", "messages": 2, "events": 3, "active_agents": 2}
            ],
            "busiest_weekdays": {"Wednesday": 2, "Monday": 5, "Sunday": 0},
            "conversation_depth": {
                "total_chains": 3,
                "max_depth": 5,
                "mean_depth": 3.7,
                "median_depth": 3.0,
            },
            "chain_initiators": [
                {"agent": "GPT-5.5", "chains": 2},
                {"agent": "Kimi K2.6", "chains": 1},
            ],
            "token_usage": {"totals": {"input": 100, "output": 25, "total": 125}},
            "top_interaction_pairs": [
                {"pair": ["GPT-5.5", "Kimi K2.6"], "count": 4},
                {"pair": ["Claude Opus 4.8", "GPT-5.5"], "count": 2},
            ],
            "interaction_rankings": {
                "top_responders": [{"agent": "GPT-5.5", "count": 2}],
                "top_targets": [{"agent": "Kimi K2.6", "count": 2}],
            },
        }

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: fake_events)
        monkeypatch.setattr(
            ac.VillageAPIClient, "_discover_latest_day", lambda self: 427
        )

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        from village_pulse.__main__ import main

        out = tmp_path / "report.md"
        rc = main(
            [
                "--format",
                "markdown",
                "--days",
                "7",
                "--room",
                "best",
                "--output",
                str(out),
            ]
        )

        assert rc == 0
        text = out.read_text(encoding="utf-8")
        assert "# Village Pulse - 7-Day Digest — #best" in text
        assert "- Room: best" in text
        assert "- Window: 7 days" in text
        assert "## Summary" in text
        assert "| Total messages | 2 |" in text
        assert "## Agent activity" in text
        assert "| GPT-5.5 | 2 |" in text
        assert "## Room participation" in text
        assert "| best | 3 | GPT-5.5: 2, Kimi K2.6: 1 |" in text
        assert "## Daily trends" in text
        assert "| 2026-06-02 | 2 | 3 | 2 |" in text
        assert "## Busiest weekdays" in text
        assert text.index("| Monday | 5 |") < text.index("| Wednesday | 2 |")
        assert "| Sunday | 0 |" in text
        assert "## Conversation depth" in text
        assert "| Total chains | 3 |" in text
        assert "| Max depth | 5 |" in text
        assert "| Mean depth | 3.7 |" in text
        assert "| Median depth | 3.0 |" in text
        assert "## Chain initiators" in text
        assert "| GPT-5.5 | 2 |" in text
        assert "| Kimi K2.6 | 1 |" in text
        assert "## Top interaction pairs" in text
        assert "| GPT-5.5 ↔ Kimi K2.6 | 4 |" in text
        assert "| Claude Opus 4.8 ↔ GPT-5.5 | 2 |" in text
        assert "## Top responders" in text
        assert "| GPT-5.5 | 2 |" in text
        assert "<svg" not in text

    def test_markdown_skips_zero_conversation_depth(self):
        """Markdown omits conversation depth when no reply chains exist."""
        from village_pulse.__main__ import _metrics_to_markdown

        text = _metrics_to_markdown(
            {
                "meta": {"total_events": 0, "total_messages": 0},
                "conversation_depth": {
                    "total_chains": 0,
                    "max_depth": 0,
                    "mean_depth": 0.0,
                    "median_depth": 0.0,
                },
                "chain_initiators": [],
            },
            context={"days": 7},
        )

        assert "## Conversation depth" not in text
        assert "## Chain initiators" not in text

    def test_markdown_stdout_when_no_output_flag(self, monkeypatch, capsys):
        """--format markdown without -o prints Markdown to stdout."""
        fake_metrics = {
            "meta": {
                "total_events": 1,
                "total_messages": 1,
                "unique_agents": 1,
                "unique_rooms": 1,
            },
            "messages_per_agent": {"A|B": 1},
        }

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: [])

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        from village_pulse.__main__ import main

        rc = main(["--format", "markdown", "--days", "1"])

        assert rc == 0
        captured = capsys.readouterr()
        assert "# Village Pulse Dashboard" in captured.out
        assert "- Window: 1 day" in captured.out
        assert "1-Day Digest" not in captured.out
        assert "A\\|B" in captured.out


class TestMainErrorHandling:
    def test_main_returns_two_when_fetch_events_raises_api_error(
        self, monkeypatch, capsys
    ):
        import village_pulse.api_client as ac

        def boom(**_kwargs):
            raise ac.APIError("api unavailable", status=503)

        monkeypatch.setattr(ac, "fetch_events", boom)

        from village_pulse.__main__ import main

        rc = main(["--format", "json", "--days", "1"])

        assert rc == 2
        captured = capsys.readouterr()
        assert "API error:" in captured.err
        assert "api unavailable" in captured.err
        assert "[HTTP 503]" in captured.err


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
        monkeypatch.setattr(
            ac.VillageAPIClient, "_discover_latest_day", lambda self: 427
        )

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: {"meta": {}})

        from village_pulse.__main__ import main

        out = tmp_path / "events.csv"
        rc = main(["--format", "csv", "--output", str(out)])

        assert rc == 0
        assert out.exists()
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        assert (
            lines[0]
            == "timestamp,agent,room,action_type,content,input_tokens,output_tokens"
        )
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
        monkeypatch.setattr(
            ac.VillageAPIClient, "_discover_latest_day", lambda self: 427
        )

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: {"meta": {}})

        from village_pulse.__main__ import main

        rc = main(["--format", "csv"])
        assert rc == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert (
            lines[0]
            == "timestamp,agent,room,action_type,content,input_tokens,output_tokens"
        )
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
        monkeypatch.setattr(
            ac.VillageAPIClient, "_discover_latest_day", lambda self: 427
        )

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: {"meta": {}})

        from village_pulse.__main__ import main

        out = tmp_path / "edge.csv"
        rc = main(["--format", "csv", "--output", str(out)])
        assert rc == 0
        text = out.read_text(encoding="utf-8")
        # The content cell should be quoted because it contains a comma and newline
        assert '"Hello, world!\nSecond line"' in text


def test_rooms_alias_includes_room_daily_trends():
    """The 'rooms' metrics alias should include the new room_daily_trends key."""
    keys = _selected_metric_keys("rooms")
    assert keys is not None
    assert "room_daily_trends" in keys


class TestCLIExtraEdges:
    def test_verbose_output(self, monkeypatch, capsys):
        """Test main when --verbose is specified."""
        fake_metrics = {"meta": {"total_events": 1}}
        fake_events = [
            {
                "agent_name": "Kimi K2.6",
                "room": "best",
                "action_type": "AGENT_TALK",
                "content": "hi",
            }
        ]

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: fake_events)
        monkeypatch.setattr(
            ac.VillageAPIClient, "_discover_latest_day", lambda self: 427
        )

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        import village_pulse.report as rp

        monkeypatch.setattr(rp, "generate", lambda **kwargs: Path("report.html"))

        from village_pulse.__main__ import main

        rc = main(["--verbose", "--format", "json"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "[village-pulse] version" in captured.out
        assert "[village-pulse] endpoint:" in captured.out
        assert "[village-pulse] fetching data..." in captured.out
        assert "[village-pulse] fetched 1 events" in captured.out
        assert "[village-pulse] computing analytics..." in captured.out

    def test_verbose_csv_output(self, monkeypatch, capsys):
        """Test verbose printing with --format csv."""
        fake_events = [
            {
                "agent_name": "Kimi",
                "room": "best",
                "action_type": "AGENT_TALK",
                "content": "hi",
            }
        ]

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: fake_events)
        monkeypatch.setattr(
            ac.VillageAPIClient, "_discover_latest_day", lambda self: 427
        )

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: {"meta": {}})

        from village_pulse.__main__ import main

        rc = main(["--verbose", "--format", "csv"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "[village-pulse] writing CSV events..." in captured.out

    def test_api_error_handling(self, monkeypatch, capsys):
        """Test that main returns 2 on APIError."""
        import village_pulse.api_client as ac

        def fake_fetch_raise(**kwargs):
            raise ac.APIError("Fake API failure")

        monkeypatch.setattr(ac, "fetch_events", fake_fetch_raise)

        from village_pulse.__main__ import main

        rc = main([])
        assert rc == 2
        captured = capsys.readouterr()
        assert "[village-pulse] API error: Fake API failure" in captured.err

    def test_unexpected_exception_handling(self, monkeypatch, capsys):
        """Test that main returns 3 on unexpected exception."""
        import village_pulse.api_client as ac

        def fake_fetch_raise_unexpected(**kwargs):
            raise ValueError("Something went terribly wrong")

        monkeypatch.setattr(ac, "fetch_events", fake_fetch_raise_unexpected)

        from village_pulse.__main__ import main

        rc = main([])
        assert rc == 3
        captured = capsys.readouterr()
        assert (
            "[village-pulse] unexpected error: Something went terribly wrong"
            in captured.err
        )

    def test_default_html_output_path(self, monkeypatch, tmp_path):
        """Test default output_path is Path('report.html') if format is html and output is None."""
        import os

        orig_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            fake_metrics = {"meta": {"total_events": 0}}
            import village_pulse.api_client as ac

            monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: [])

            import village_pulse.analytics as an

            monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

            import village_pulse.report as rp

            generate_calls = []

            def fake_generate(**kwargs):
                generate_calls.append(kwargs)
                p = Path("report.html")
                p.write_text("dummy html", encoding="utf-8")
                return p

            monkeypatch.setattr(rp, "generate", fake_generate)

            from village_pulse.__main__ import main

            rc = main([])
            assert rc == 0
            assert len(generate_calls) == 1
            assert generate_calls[0]["output_path"] == Path("report.html")
            assert Path("report.html").exists()
        finally:
            os.chdir(orig_cwd)

    def test_verbose_html_output(self, monkeypatch, capsys):
        """Test verbose printing with HTML report generation."""
        fake_metrics = {"meta": {"total_events": 1}}
        fake_events = [
            {
                "agent_name": "Kimi K2.6",
                "room": "best",
                "action_type": "AGENT_TALK",
                "content": "hi",
            }
        ]

        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: fake_events)
        monkeypatch.setattr(
            ac.VillageAPIClient, "_discover_latest_day", lambda self: 427
        )

        import village_pulse.analytics as an

        monkeypatch.setattr(an, "compute_all", lambda _events: fake_metrics)

        import village_pulse.report as rp

        monkeypatch.setattr(rp, "generate", lambda **kwargs: Path("report.html"))

        from village_pulse.__main__ import main

        rc = main(["--verbose"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "[village-pulse] generating report..." in captured.out


class TestCLIInternalEdgeCases:
    def test_markdown_escape_none(self):
        from village_pulse.__main__ import _markdown_escape

        assert _markdown_escape(None) == ""

    def test_metrics_to_markdown_various_contexts(self):
        from village_pulse.__main__ import _metrics_to_markdown

        metrics = {
            "meta": {"total_events": 5, "total_messages": 3},
            "room_participation": {"best": 12},
        }
        # 1. room but no day (Line 98)
        md1 = _metrics_to_markdown(metrics, context={"room": "best", "days": 1})
        assert "# Village Pulse — #best" in md1
        # 2. days > 1 but no room (Line 101)
        md2 = _metrics_to_markdown(metrics, context={"days": 7})
        assert "# Village Pulse - 7-Day Digest" in md2
        # 3. days > 1 with a room keeps both digest and room scope visible
        md_room_digest = _metrics_to_markdown(
            metrics, context={"room": "best", "days": 7}
        )
        assert "# Village Pulse - 7-Day Digest — #best" in md_room_digest
        # 4. explicit day with a room uses the single-day day title
        md_room_day = _metrics_to_markdown(
            metrics, context={"room": "best", "days": 1, "day": 427}
        )
        assert "# Village Pulse — Day 427 — #best" in md_room_day
        # 5. context agent specified (Line 113)
        md3 = _metrics_to_markdown(metrics, context={"agent": "GPT-5.5"})
        assert "- Agent: GPT-5.5" in md3
        # 6. non-dict room participation value (Lines 144-145)
        assert "| best | 12 |" in md3

    def test_main_discover_latest_day_exception(self, monkeypatch):
        import village_pulse.api_client as ac

        def fake_discover(self):
            raise ValueError("API Offline")

        monkeypatch.setattr(ac.VillageAPIClient, "_discover_latest_day", fake_discover)
        monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: [])

        from village_pulse.__main__ import main

        # should catch the exception and run main successfully without crash
        rc = main(["--room", "best"])
        assert rc == 0

    def test_main_markdown_verbose(self, monkeypatch, capsys):
        import village_pulse.api_client as ac

        monkeypatch.setattr(ac, "fetch_events", lambda **kwargs: [])
        monkeypatch.setattr(
            ac.VillageAPIClient, "_discover_latest_day", lambda self: 427
        )

        from village_pulse.__main__ import main

        rc = main(["--format", "markdown", "--verbose", "--room", "best"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "[village-pulse] writing Markdown report..." in captured.out

    def test_markdown_busiest_weekdays_edge_cases(self):
        from village_pulse.__main__ import _metrics_to_markdown

        metrics = {
            "meta": {"total_events": 0, "total_messages": 0},
            "busiest_weekdays": [
                {"weekday": "Friday", "count": "2"},
                {"day": "Tuesday", "count": 5},
                ["Monday", 3],
                {"weekday": "Funday", "count": "bad"},
                "not-a-row",
            ],
        }
        text = _metrics_to_markdown(metrics, context={"days": 1})
        assert "## Busiest weekdays" in text
        assert text.index("| Monday | 3 |") < text.index("| Tuesday | 5 |")
        assert text.index("| Tuesday | 5 |") < text.index("| Friday | 2 |")
        assert "| Funday | 0 |" in text
        assert "not-a-row" not in text

    def test_markdown_top_interaction_pairs_edge_cases(self):
        from village_pulse.__main__ import _metrics_to_markdown

        metrics = {
            "meta": {"total_events": 0, "total_messages": 0},
            "top_interaction_pairs": [
                "not-a-dict",
                {"pair": ["Alice"], "count": 5},  # pair too short (len < 2)
                {"pair": ["Alice", "Bob"], "count": 10},  # valid
            ],
        }
        text = _metrics_to_markdown(metrics, context={"days": 1})
        assert "## Top interaction pairs" in text
        assert "Alice ↔ Bob" in text
        assert "10" in text
        assert "not-a-dict" not in text
