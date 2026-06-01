"""Village Pulse CLI — fetch, analyze, and generate an activity dashboard."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from village_pulse import __version__


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
        default=Path("report.html"),
        help="Output HTML report path (default: report.html)",
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
        choices=["html", "json"],
        default="html",
        help="Output format (default: html)",
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

    if args.verbose:
        print(f"[village-pulse] version {__version__}")
        print(f"[village-pulse] endpoint: {args.endpoint}")
        print(f"[village-pulse] days: {args.days}")
        print(f"[village-pulse] room: {args.room or 'all'}")
        print(f"[village-pulse] agent: {args.agent or 'all'}")
        print(f"[village-pulse] output: {args.output}")

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

        if args.format == "json":
            if args.verbose:
                print("[village-pulse] writing JSON metrics...")
            args.output.write_text(
                json.dumps(metrics, indent=2, default=str),
                encoding="utf-8",
            )
        else:
            if args.verbose:
                print("[village-pulse] generating report...")
            report.generate(
                metrics=metrics,
                output_path=args.output,
                context={
                    "room": args.room,
                    "days": args.days,
                    "agent": args.agent,
                    "version": __version__,
                },
            )

        print(f"[village-pulse] report written to {args.output.resolve()}")
        return 0

    except api_client.APIError as exc:
        print(f"[village-pulse] API error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[village-pulse] unexpected error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
