"""Village Pulse CLI — fetch, analyze, and generate an activity dashboard."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from village_pulse import __version__


_METRIC_ALIASES = {
    "messages": {
        "messages_per_agent",
        "messages_per_agent_per_day",
        "messages_per_day",
    },
    "tokens": {"token_usage"},
    "rooms": {
        "room_participation",
        "room_participation_rates",
        "room_health",
        "room_daily_trends",
    },
    "activity": {
        "active_agents",
        "agent_last_seen",
        "busiest_hours",
        "busiest_weekdays",
        "action_type_breakdown",
        "daily_trends",
        "agent_daily_trends",
        "top_agents_over_time",
        "room_daily_trends",
    },
}


def _selected_metric_keys(metrics_arg: str) -> set[str] | None:
    """Return selected metric keys, expanding friendly aliases, or None for all."""
    requested = {item.strip() for item in metrics_arg.split(",") if item.strip()}
    if not requested or requested == {"all"}:
        return None
    selected = {"meta"}
    for item in requested:
        selected.update(_METRIC_ALIASES.get(item, {item}))
    return selected


def _filter_metrics(metrics: dict, metrics_arg: str) -> dict:
    selected = _selected_metric_keys(metrics_arg)
    if selected is None:
        return metrics
    return {key: value for key, value in metrics.items() if key in selected}


def _events_to_csv(events: list[dict]) -> str:
    """Serialize flat event dicts to CSV text."""
    import io

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        [
            "timestamp",
            "agent",
            "room",
            "action_type",
            "content",
            "input_tokens",
            "output_tokens",
        ]
    )
    for ev in events:
        writer.writerow(
            [
                ev.get("created_at") or "",
                ev.get("agent_name") or "",
                ev.get("room") or "",
                ev.get("action_type") or "",
                ev.get("content") or "",
                ev.get("input_tokens") if ev.get("input_tokens") is not None else "",
                ev.get("output_tokens") if ev.get("output_tokens") is not None else "",
            ]
        )
    return out.getvalue()


def _markdown_escape(value: object) -> str:
    """Return a compact Markdown-safe string for table cells."""
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ")
    return text.replace("|", "\\|")


def _markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    """Build a GitHub-flavored Markdown table."""
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_markdown_escape(cell) for cell in row) + " |")
    return lines


def _metrics_to_markdown(metrics: dict, *, context: dict) -> str:
    """Render key dashboard metrics as a clean Markdown document."""
    days = context.get("days")
    if isinstance(days, int) and days > 1:
        title = f"Village Pulse - {days}-Day Digest"
    else:
        title = "Village Pulse Dashboard"

    room_val = context.get("room")
    if room_val:
        room_str = str(room_val)
        if not room_str.startswith("#"):
            room_str = "#" + room_str
        day_val = context.get("day")
        if day_val is not None:
            title = f"Village Pulse — Day {day_val} — {room_str}"
        elif isinstance(days, int) and days > 1:
            title = f"{title} — {room_str}"
        else:
            title = f"Village Pulse — {room_str}"

    meta = metrics.get("meta") if isinstance(metrics.get("meta"), dict) else {}
    lines = [f"# {title}", ""]
    scope = context.get("room") or "All rooms"
    lines.extend(
        [
            f"- Room: {scope}",
            f"- Window: {days} day{'s' if days != 1 else ''}"
            if days
            else "- Window: not specified",
        ]
    )
    if context.get("agent"):
        lines.append(f"- Agent: {context['agent']}")
    if context.get("version"):
        lines.append(f"- Version: {context['version']}")
    lines.append("")

    summary_rows = [
        ["Total events", meta.get("total_events", 0)],
        ["Total messages", meta.get("total_messages", 0)],
        ["Unique agents", meta.get("unique_agents", 0)],
        ["Unique rooms", meta.get("unique_rooms", 0)],
    ]
    lines.extend(["## Summary", ""])
    lines.extend(_markdown_table(["Metric", "Value"], summary_rows))
    lines.append("")

    messages = metrics.get("messages_per_agent")
    if isinstance(messages, dict) and messages:
        rows = [
            [agent, count]
            for agent, count in sorted(
                messages.items(),
                key=lambda item: (-int(item[1] or 0), str(item[0]).lower()),
            )
        ]
        lines.extend(["## Agent activity", ""])
        lines.extend(_markdown_table(["Agent", "Messages"], rows))
        lines.append("")

    rooms = metrics.get("room_participation")
    if isinstance(rooms, dict) and rooms:
        room_rows = []
        for room, value in rooms.items():
            if isinstance(value, dict):
                total = sum(int(count or 0) for count in value.values())
                top_agents = sorted(
                    value.items(),
                    key=lambda item: (-int(item[1] or 0), str(item[0]).lower()),
                )[:3]
                detail = ", ".join(f"{agent}: {count}" for agent, count in top_agents)
            else:
                total = int(value or 0)
                detail = ""
            room_rows.append([room, total, detail])
        rows = sorted(
            room_rows, key=lambda row: (-int(row[1] or 0), str(row[0]).lower())
        )
        lines.extend(["## Room participation", ""])
        lines.extend(_markdown_table(["Room", "Messages", "Top agents"], rows))
        lines.append("")

    daily = metrics.get("daily_trends")
    if isinstance(daily, list) and daily:
        rows = []
        for item in daily:
            if isinstance(item, dict):
                rows.append(
                    [
                        item.get("date", ""),
                        item.get("messages", 0),
                        item.get("events", 0),
                        item.get("active_agents", 0),
                    ]
                )
        if rows:
            lines.extend(["## Daily trends", ""])
            lines.extend(
                _markdown_table(["Date", "Messages", "Events", "Active agents"], rows)
            )
            lines.append("")

    token_usage = metrics.get("token_usage")
    if isinstance(token_usage, dict):
        totals = token_usage.get("totals")
        if isinstance(totals, dict) and totals:
            lines.extend(["## Token usage", ""])
            lines.extend(
                _markdown_table(
                    ["Metric", "Value"], [[key, value] for key, value in totals.items()]
                )
            )
            lines.append("")

    rankings = metrics.get("interaction_rankings")
    if isinstance(rankings, dict):
        top_responders = rankings.get("top_responders")
        top_targets = rankings.get("top_targets")
        if isinstance(top_responders, list) and top_responders:
            lines.extend(["## Top responders", ""])
            rows = [
                [item.get("agent", ""), item.get("count", 0)]
                for item in top_responders
                if isinstance(item, dict)
            ]
            lines.extend(_markdown_table(["Agent", "Replies made"], rows))
            lines.append("")
        if isinstance(top_targets, list) and top_targets:
            lines.extend(["## Top targets", ""])
            rows = [
                [item.get("agent", ""), item.get("count", 0)]
                for item in top_targets
                if isinstance(item, dict)
            ]
            lines.extend(_markdown_table(["Agent", "Replies received"], rows))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="village-pulse",
        description="Real-time village activity monitoring and analytics dashboard generator.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output path (default: report.html for html, stdout for json)",
    )
    parser.add_argument(
        "--room",
        type=str,
        default=None,
        help="Specific room name to analyze (default: all rooms)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of past days to include in analysis (default: 7)",
    )
    parser.add_argument(
        "--day",
        type=int,
        default=None,
        help="Specific village day to use as the end of the analysis window (overrides auto-discovery)",
    )
    parser.add_argument(
        "--agent",
        type=str,
        default=None,
        help="Filter to a specific agent name",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default="https://theaidigest.org/village/api/",
        help="Base URL for the village API",
    )
    parser.add_argument(
        "--format",
        choices=["html", "json", "csv", "markdown"],
        default="html",
        help="Output format (default: html)",
    )
    parser.add_argument(
        "--metrics",
        type=str,
        default="all",
        help="Comma-separated metric keys or aliases to include: messages, tokens, rooms, activity, all (default: all)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.days < 1:
        print("[village-pulse] error: --days must be >= 1", file=sys.stderr)
        return 1
    if args.day is not None and args.day < 1:
        print("[village-pulse] error: --day must be >= 1", file=sys.stderr)
        return 1

    output_path: Path | None = args.output
    if output_path is None:
        if args.format == "html":
            output_path = Path("report.html")
        else:
            output_path = None

    if args.verbose:
        print(f"[village-pulse] version {__version__}")
        print(f"[village-pulse] endpoint: {args.endpoint}")
        print(f"[village-pulse] days: {args.days}")
        print(f"[village-pulse] room: {args.room or 'all'}")
        print(f"[village-pulse] agent: {args.agent or 'all'}")
        print(f"[village-pulse] output: {output_path or 'stdout'}")

    try:
        from village_pulse import api_client, analytics, report
    except ImportError as exc:
        print(
            f"[village-pulse] error: missing module dependency – {exc}\n"
            "Make sure api_client.py, analytics.py, and report.py are available.",
            file=sys.stderr,
        )
        return 1

    try:
        if args.verbose:
            print("[village-pulse] fetching data...")
        latest_day = args.day
        if latest_day is None and args.room is not None:
            try:
                client = api_client.VillageAPIClient(endpoint=args.endpoint)
                latest_day = client._discover_latest_day()
            except Exception:
                latest_day = None
        raw_events = api_client.fetch_events(
            endpoint=args.endpoint,
            days=args.days,
            room=args.room,
            agent=args.agent,
            current_day=latest_day,
        )

        if args.verbose:
            print(f"[village-pulse] fetched {len(raw_events)} events")
            print("[village-pulse] computing analytics...")
        metrics = analytics.compute_all(raw_events)

        metrics = _filter_metrics(metrics, args.metrics)
        title_day = latest_day if args.days == 1 else None

        if args.format == "csv":
            if args.verbose:
                print("[village-pulse] writing CSV events...")
            csv_text = _events_to_csv(raw_events)
            if output_path is None:
                print(csv_text, end="")
            else:
                output_path.write_text(csv_text, encoding="utf-8")
                print(f"[village-pulse] CSV written to {output_path.resolve()}")
            return 0

        if args.format == "json":
            if args.verbose:
                print("[village-pulse] writing JSON metrics...")
            json_text = json.dumps(metrics, indent=2, default=str)
            if output_path is None:
                print(json_text)
            else:
                output_path.write_text(json_text, encoding="utf-8")
                print(f"[village-pulse] JSON written to {output_path.resolve()}")
        elif args.format == "markdown":
            if args.verbose:
                print("[village-pulse] writing Markdown report...")
            markdown_text = _metrics_to_markdown(
                metrics,
                context={
                    "room": args.room,
                    "days": args.days,
                    "agent": args.agent,
                    "version": __version__,
                    "day": title_day,
                },
            )
            if output_path is None:
                print(markdown_text, end="")
            else:
                output_path.write_text(markdown_text, encoding="utf-8")
                print(f"[village-pulse] Markdown written to {output_path.resolve()}")
        else:
            if args.verbose:
                print("[village-pulse] generating report...")
            report.generate(
                metrics=metrics,
                output_path=output_path,
                context={
                    "room": args.room,
                    "days": args.days,
                    "agent": args.agent,
                    "version": __version__,
                    "day": title_day,
                },
            )
            print(f"[village-pulse] report written to {output_path.resolve()}")

        return 0

    except api_client.APIError as exc:
        print(f"[village-pulse] API error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[village-pulse] unexpected error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
