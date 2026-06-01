"""Village Pulse CLI — fetch, analyze, and generate an activity dashboard."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from village_pulse import __version__


_METRIC_ALIASES = {
    "messages": {"messages_per_agent", "messages_per_agent_per_day", "messages_per_day"},
    "tokens": {"token_usage"},
    "rooms": {"room_participation", "room_participation_rates", "room_health"},
    "activity": {
        "active_agents",
        "agent_last_seen",
        "busiest_hours",
        "busiest_weekdays",
        "action_type_breakdown",
        "daily_trends",
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
    writer.writerow(["timestamp", "agent", "room", "action_type", "content", "input_tokens", "output_tokens"])
    for ev in events:
        writer.writerow([
            ev.get("created_at") or "",
            ev.get("agent_name") or "",
            ev.get("room") or "",
            ev.get("action_type") or "",
            ev.get("content") or "",
            ev.get("input_tokens") if ev.get("input_tokens") is not None else "",
            ev.get("output_tokens") if ev.get("output_tokens") is not None else "",
        ])
    return out.getvalue()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="village-pulse",
        description="Real-time village activity monitoring and analytics dashboard generator.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
        choices=["html", "json", "csv"],
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
        raw_events = api_client.fetch_events(
            endpoint=args.endpoint,
            days=args.days,
            room=args.room,
            agent=args.agent,
        )

        if args.verbose:
            print(f"[village-pulse] fetched {len(raw_events)} events")
            print("[village-pulse] computing analytics...")
        metrics = analytics.compute_all(raw_events)

        metrics = _filter_metrics(metrics, args.metrics)

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


if __name__ == "__main__":
    sys.exit(main())
