"""Tests for the village_pulse CLI entry point."""

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
