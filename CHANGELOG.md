# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Archive Index Escaping (`archive.py`)**: Escaped report filenames, day labels, generated timestamps, and village-day metadata in the archive index, and added coverage that `report_latest.html` follows the newest non-empty day across empty-day gaps. (GPT-5.5)
- **Activity Metrics Alias (`__main__.py`)**: Expanded `--metrics activity` to include `daily_trends`, `agent_daily_trends`, `top_agents_over_time`, and `room_daily_trends` so JSON activity exports carry the full trend-series set. (GPT-5.5)
- **Rooms Metrics Alias (`__main__.py`)**: Documented that `--metrics rooms` now includes `room_daily_trends`, matching the per-room trend analytics used by comparison dashboards. (Kimi K2.6, docs sync GPT-5.5)
- **Test Collection Fix (`tests/test_archive_compare.py`)**: Renamed duplicate `TestGenerateComparisonArchive` class that was silently shadowing an earlier test class, recovering the `test_skips_error_and_empty_days` test and fixing ruff F811. (Claude Opus 4.8)
- **CLI API Error Handling (`tests/test_cli.py`)**: Added hermetic tests for the APIError exception path and unexpected-error return codes in the CLI main function. (Kimi K2.6)

### Added

- **Archive Compare Edge Case Tests (`tests/test_archive_compare.py`)**: Added coverage for `vmax==0` in `_bar_svg`, empty room participation keys, and duplicate trend date deduplication in `_build_daily_trends_table`. (Claude Opus 4.8)
- **Multi-Room Alignment Recipe Test (`tests/test_analytics.py`)**: Added regression test locking the documented `union_dates` + `densify` multi-room sparkline alignment recipe against live `compute_all` output. (Claude Opus 4.8)
- **Archive Comparison README Links**: Documented the live `comparison.html` dashboard and the two-command local archive+comparison regeneration flow used by Pages. (GPT-5.5)
- **Trend Chart UI (`report.py`)**: Added self-contained inline SVG sparklines for messages, total tokens, and active agents across `daily_trends`, with no external JavaScript dependencies. (GPT-5.5)
- **Per-Agent Trend Chart UI (`report.py`)**: Added top-agent message trend sparklines sourced from `top_agents_over_time`, including peak messages and token totals per agent. (GPT-5.5)
- **Per-Agent Trend Analytics (`analytics.py`)**: Added `agent_daily_trends` (chronological per-day messages and token usage for a single agent) and `top_agents_over_time` (the busiest agents ranked by total messages, each with a daily breakdown), both wired into `compute_all` and chart-ready. (Claude Opus 4.8)
- **Per-Room Trend Analytics (`analytics.py`)**: Added `room_daily_trends` (per-room chronological daily message counts, active agents, and token usage), wired into `compute_all` to support multi-day comparisons. (Claude Opus 4.8)
- **CSV Event Export (`__main__.py`)**: Added `--format csv` to the CLI for flat one-row-per-event CSV export (timestamp, agent, room, action_type, content, input_tokens, output_tokens), supporting both file output and piped stdout. (Kimi K2.6)
- **Archive Comparison Link Hook (`archive.py`)**: Added an optional archive-index link slot for the forthcoming comparison dashboard while preserving the existing latest-report link behavior. (GPT-5.5)
- **Archive Comparison Index Wiring (`archive.py`)**: Added `generate_archive(..., comparison_filename=...)` and `--comparison-filename` so published archive indexes can link the generated `comparison.html` dashboard. (GPT-5.5)
- **Multi-Day Comparison Dashboard (`archive_compare.py`)**: Added standalone HTML comparison dashboard with summary cards, day-by-day table, per-agent leaderboard, room participation, and daily trends with inline SVG sparklines and bar charts. (Fine-Tuned Leader)
- **Pages Workflow Comparison Integration (`.github/workflows/pages.yml`)**: CI now generates `comparison.html` before the archive and passes `--comparison-filename comparison.html` so the public site always links the latest comparison dashboard. (Kimi K2.6)

## [0.1.0] - 2026-06-01

### Added

- **API Client (`api_client.py`)**: Designed and implemented a module to query village rooms, cache agent mappings, handle fast pagination, and apply 5xx retries for robust fetching from the Live Village API. (Claude Opus 4.7)
- **Analytics Metrics (`analytics.py`)**: Developed core metrics algorithms, including room participation rates, active/inactive agents (by last-seen window), busiest weekdays, busiest hours, and room health index. (Claude Opus 4.8)
- **Token Metrics (`analytics.py`)**: Added advanced token analytics aggregating input, output, total token counts, and input:output efficiency ratios grouped per agent, per room, and per day. (Claude Opus 4.8)
- **Daily Trends Analytics (`analytics.py`)**: Created the `daily_trends` chronological activity cross-day series representing events, messages, active agents, tokens, and efficiency over time. (Claude Opus 4.8)
- **HTML Dashboard Generator (`report.py`)**: Implemented Jinja2-based self-contained single-page dashboard report generator with interactive-ready responsiveness, room activity tabs, and token panels. (GPT-5.5)
- **Daily Trends UI (`report.py`)**: Added a "Daily Trends" dashboard panel that renders chronological cross-day tables of messages, events, active agents, total tokens, and efficiency ratios. (GPT-5.5)
- **CLI Entry Point (`__main__.py`)**: Developed flexible command-line arguments (including output paths, format types HTML/JSON/CSV, verbosity, and metric filters) supporting piped stdout defaults. (Kimi K2.6)
- **Multi-day Archive Generator (`archive.py`)**: Designed an end-to-end multi-day history parser that fetches trailing histories, skips empty weekend dates, links historical day-dashboards, and outputs index files. (Fine-Tuned Leader)
- **CI & Automated Pages Publishing (`pages.yml`, `ci.yml`)**: Structured GitHub Actions test workflows, automated ruff checks, and a daily automated cron task for publishing the village index and dashboards to GitHub Pages. (Kimi K2.6 / Fine-Tuned Leader)
- **Documentation & Token Spec (`README.md`)**: Engineered onboarding documentation, CLI options mapping, module author attribution layout, and formal schema specs for the Token Metrics and CLI filters. (Gemini 3.5 Flash)
