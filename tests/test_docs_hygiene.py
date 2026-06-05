from pathlib import Path
import re
from urllib.parse import unquote


DOC_PATHS = [
    Path("README.md"),
    Path("CHANGELOG.md"),
    *sorted(Path("docs").glob("*.md")),
]


UNBACKTICKED_GIT_LOG_FRAGMENT = re.compile(
    r"(?<![`A-Za-z0-9_])(?P<sha>[0-9a-f]{7,40})\s+\(.*:.*\)"
)
MARKDOWN_LINK = re.compile(r"(?<!\!)\[[^\]]+\]\((?P<target>[^)]+)\)")
EXTERNAL_LINK_PREFIXES = ("http://", "https://", "mailto:", "#")


def test_markdown_docs_do_not_contain_pasted_git_log_fragments():
    """Catch accidental raw `git log --oneline` fragments in prose docs."""
    offenders = []
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if UNBACKTICKED_GIT_LOG_FRAGMENT.search(line):
                offenders.append(f"{path}:{line_no}: {line.strip()}")

    assert offenders == []


def _local_markdown_link_target(target: str) -> str | None:
    target = target.strip()
    if not target or target.startswith(EXTERNAL_LINK_PREFIXES):
        return None
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if target.startswith(EXTERNAL_LINK_PREFIXES):
        return None
    return unquote(target.split("#", 1)[0])


def test_markdown_docs_do_not_link_to_missing_local_files():
    """Catch stale local Markdown links after docs/files are renamed."""
    offenders = []
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for match in MARKDOWN_LINK.finditer(line):
                target = _local_markdown_link_target(match.group("target"))
                if target is None:
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    offenders.append(f"{path}:{line_no}: missing local link {target}")

    assert offenders == []


def test_git_log_fragment_pattern_matches_accidental_oneline_paste():
    line = "13d1951 (docs(readme+changelog): describe new comparison sections)"

    assert UNBACKTICKED_GIT_LOG_FRAGMENT.search(line)
    assert not UNBACKTICKED_GIT_LOG_FRAGMENT.search(
        "Use `13d1951 (docs(readme): example)` only inside backticks"
    )


def test_markdown_docs_with_offenders(tmp_path, monkeypatch):
    import pytest
    import sys

    tdh = sys.modules[__name__]
    fake_doc = tmp_path / "test_offender.md"
    fake_doc.write_text("13d1951 (docs(readme): mock description)", encoding="utf-8")
    monkeypatch.setattr(tdh, "DOC_PATHS", [fake_doc])
    with pytest.raises(AssertionError) as exc_info:
        tdh.test_markdown_docs_do_not_contain_pasted_git_log_fragments()
    assert "test_offender.md:1" in str(exc_info.value)


def test_markdown_local_link_check_reports_missing_file(tmp_path, monkeypatch):
    import pytest
    import sys

    tdh = sys.modules[__name__]
    fake_doc = tmp_path / "doc.md"
    fake_doc.write_text(
        "See [missing](missing.md) and [external](https://example.com).",
        encoding="utf-8",
    )
    monkeypatch.setattr(tdh, "DOC_PATHS", [fake_doc])

    with pytest.raises(AssertionError) as exc_info:
        tdh.test_markdown_docs_do_not_link_to_missing_local_files()

    assert "missing local link missing.md" in str(exc_info.value)
    assert "https://example.com" not in str(exc_info.value)


def test_readme_documents_room_filter_and_csv_room_normalization():
    """Keep README guidance aligned with CLI room filter and CSV output behavior."""
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "room may be written as best or #best" in readme
    assert "`--room`" in readme
    assert "accepts either `best` or `#best`" in readme
    assert "CSV `room` column uses the API's normalized room name" in readme
    assert "even when the input filter is written as `--room #best`" in readme


def test_analytics_contract_documents_every_compute_all_key():
    """Catch missing contract entries when compute_all adds or renames metrics."""
    from village_pulse.analytics import compute_all

    sample_events = [
        {
            "createdAt": "2026-06-01T00:00:00Z",
            "data": {
                "actionType": "AGENT_TALK",
                "agentName": "Alice",
                "roomName": "best",
                "content": "hi",
                "inputTokens": 1,
                "outputTokens": 1,
            },
        },
        {
            "createdAt": "2026-06-01T00:01:00Z",
            "data": {
                "actionType": "AGENT_TALK",
                "agentName": "Bob",
                "roomName": "best",
                "content": "reply",
                "inputTokens": 2,
                "outputTokens": 1,
            },
        },
    ]
    contract = Path("docs/analytics_contract.md").read_text(encoding="utf-8")

    missing = [key for key in compute_all(sample_events) if f"`{key}`" not in contract]

    assert missing == []
