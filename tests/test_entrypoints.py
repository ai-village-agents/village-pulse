import runpy
import sys

import pytest


@pytest.mark.parametrize(
    ("module_name", "args", "expected_output"),
    [
        ("village_pulse.__main__", ["--version"], "village-pulse"),
        (
            "village_pulse.archive",
            ["--help"],
            "Generate a multi-day Village Pulse archive",
        ),
        (
            "village_pulse.archive_compare",
            ["--help"],
            "Generate a multi-day Village Pulse comparison dashboard",
        ),
    ],
)
def test_module_entrypoint_exits_cleanly(module_name, args, expected_output, monkeypatch, capsys):
    """Ensure documented `python -m ...` entrypoints start and exit cleanly."""
    monkeypatch.setattr(sys, "argv", [module_name, *args])
    monkeypatch.delitem(sys.modules, module_name, raising=False)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)

    assert exc_info.value.code == 0
    assert expected_output in capsys.readouterr().out
