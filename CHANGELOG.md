# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Per-Agent Trend Analytics (`analytics.py`)**: Added `agent_daily_trends` (chronological per-day messages and token usage for a single agent) and `top_agents_over_time` (the busiest agents ranked by total messages, each with a daily breakdown), both wired into `compute_all` and chart-ready. (Claude Opus 4.8)

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
