from pathlib import Path
import re


DOC_PATHS = [
    Path("README.md"),
    Path("CHANGELOG.md"),
    *sorted(Path("docs").glob("*.md")),
]


UNBACKTICKED_GIT_LOG_FRAGMENT = re.compile(
    r"(?<![`A-Za-z0-9_])(?P<sha>[0-9a-f]{7,40})\s+\(.*:.*\)"
)

def test_markdown_docs_do_not_contain_pasted_git_log_fragments():
    """Catch accidental raw `git log --oneline` fragments in prose docs."""
    offenders = []
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if UNBACKTICKED_GIT_LOG_FRAGMENT.search(line):
                offenders.append(f"{path}:{line_no}: {line.strip()}")

    assert offenders == []


def test_git_log_fragment_pattern_matches_accidental_oneline_paste():
    line = "13d1951 (docs(readme+changelog): describe new comparison sections)"

    assert UNBACKTICKED_GIT_LOG_FRAGMENT.search(line)
    assert not UNBACKTICKED_GIT_LOG_FRAGMENT.search(
        "Use `13d1951 (docs(readme): example)` only inside backticks"
    )
