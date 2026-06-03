"""village_pulse.archive_compare — Multi-day comparison dashboard generator.

Generates a single HTML page that compares activity across multiple village
days with sparkline charts, agent leaderboards, and room participation trends.

Typical use::

    from village_pulse import archive_compare
    archive_compare.generate_comparison_archive("./_site", days_back=30)
"""

from __future__ import annotations

import argparse
import html as html_lib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from village_pulse import analytics, api_client

LOG = logging.getLogger(__name__)

DEFAULT_DAYS_BACK = 30


def _sparkline_svg(values, width=200, height=40):
    """Render a simple SVG sparkline from a list of numeric values."""
    if not values or all(v == 0 for v in values):
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<text x="4" y="{height // 2 + 4}" font-size="11" fill="#94a3b8">no data</text>'
            f"</svg>"
        )

    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        vmax = vmin + 1

    pad = 4
    plot_w = width - pad * 2
    plot_h = height - pad * 2

    points = []
    for i, v in enumerate(values):
        x = pad + (i / max(1, len(values) - 1)) * plot_w
        y = pad + plot_h - ((v - vmin) / (vmax - vmin)) * plot_h
        points.append(f"{x:.1f},{y:.1f}")

    points_str = " ".join(points)
    last_y = pad + plot_h - ((values[-1] - vmin) / (vmax - vmin)) * plot_h

    # Single value: center the marker for a cleaner look
    if len(values) == 1:
        cx = width / 2
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<circle cx="{cx:.1f}" cy="{last_y:.1f}" r="4" fill="#2f6fed"/>'
            f"</svg>"
        )

    last_x = pad + plot_w
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{points_str}" fill="none" stroke="#2f6fed" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="#2f6fed"/>'
        f"</svg>"
    )


def _bar_svg(values, labels, width=300, height=120):
    """Render a simple SVG bar chart."""
    if not values or all(v == 0 for v in values):
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<text x="4" y="{height // 2 + 4}" font-size="11" fill="#94a3b8">no data</text>'
            f"</svg>"
        )

    vmax = max(values)
    if vmax == 0:
        vmax = 1

    bar_w = max(10, (width - 40) // max(1, len(values)))
    max_bar_h = height - 40
    pad_x = 20

    bars = []
    colors = [
        "#2f6fed",
        "#7c3aed",
        "#17803d",
        "#b7791f",
        "#e11d48",
        "#0891b2",
        "#be185d",
        "#4338ca",
    ]
    for i, (v, label) in enumerate(zip(values, labels)):
        bh = (v / vmax) * max_bar_h if vmax > 0 else 0
        x = pad_x + i * bar_w
        y = height - 20 - bh
        color = colors[i % len(colors)]
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_w - 4}" height="{bh}" '
            f'rx="3" fill="{color}" opacity="0.8"/>'
            f'<text x="{x + (bar_w - 4) / 2}" y="{height - 6}" font-size="9" '
            f'fill="#64748b" text-anchor="middle">{html_lib.escape(str(label))}</text>'
        )

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">' + "".join(bars) + "</svg>"
    )


def _format_number(n):
    """Format a number with commas."""
    if isinstance(n, float):
        return f"{n:,.1f}"
    return f"{n:,}"


_CSS = """
:root {
  --bg: #f8fafc;
  --card-bg: #ffffff;
  --text: #0f172a;
  --text-secondary: #475569;
  --muted: #94a3b8;
  --border: #e2e8f0;
  --brand: #2f6fed;
  --brand-light: #dbeafe;
  --purple: #7c3aed;
  --green: #17803d;
  --header-bg: #0f172a;
  --header-text: #f8fafc;
  --radius: 12px;
  --shadow: 0 1px 3px rgba(0,0,0,0.08);
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  margin: 0; padding: 0; line-height: 1.5;
}
header {
  background: var(--header-bg);
  color: var(--header-text);
  padding: 24px 32px;
}
header h1 { margin: 0 0 4px 0; font-size: 1.6rem; font-weight: 600; }
header p { margin: 0; color: #94a3b8; font-size: 0.9rem; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px 32px; }
.section { margin-bottom: 32px; }
.section h2 { font-size: 1.15rem; margin: 0 0 16px 0; color: var(--text); }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 32px; }
.card {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px; box-shadow: var(--shadow);
}
.card-title { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 8px; }
.card-value { font-size: 1.6rem; font-weight: 700; color: var(--text); margin-bottom: 8px; }
.card-spark { margin-top: 8px; }
table { width: 100%; border-collapse: collapse; background: var(--card-bg); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; font-size: 0.9rem; }
th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); }
th { background: #f1f5f9; font-weight: 600; color: var(--text-secondary); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.03em; }
tr:last-child td { border-bottom: none; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.spark-cell { width: 220px; }
.leaderboard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
@media (max-width: 800px) {
  .leaderboard-grid { grid-template-columns: 1fr; }
  .container { padding: 16px; }
}
.rank { display: inline-block; width: 22px; height: 22px; line-height: 22px; text-align: center; border-radius: 50%; font-size: 0.7rem; font-weight: 700; margin-right: 8px; }
.rank-1 { background: #fde68a; color: #92400e; }
.rank-2 { background: #e2e8f0; color: #334155; }
.rank-3 { background: #fed7aa; color: #9a3412; }
.rank-other { background: #f1f5f9; color: #64748b; }
"""


def _build_summary_cards(day_metrics):
    """Build summary stat cards with sparklines."""
    messages = [d.get("messages", 0) for d in day_metrics]
    events = [d.get("events", 0) for d in day_metrics]
    agents = [d.get("agents", 0) for d in day_metrics]

    cards = [
        ("Total Messages", _format_number(messages[-1]) if messages else "0", messages),
        ("Total Events", _format_number(events[-1]) if events else "0", events),
        ("Active Agents", _format_number(agents[-1]) if agents else "0", agents),
    ]

    parts = []
    for title, value, series in cards:
        svg = _sparkline_svg(series)
        parts.append(
            f'<div class="card">'
            f'<div class="card-title">{title}</div>'
            f'<div class="card-value">{value}</div>'
            f'<div class="card-spark">{svg}</div>'
            f"</div>"
        )
    return '<div class="summary-grid">' + "".join(parts) + "</div>"


def _build_comparison_table(day_metrics):
    """Build side-by-side day comparison table."""
    rows = []
    for d in day_metrics:
        day = d.get("day", "?")
        rows.append(
            f"<tr>"
            f"<td><strong>Day {html_lib.escape(str(day))}</strong></td>"
            f'<td class="num">{_format_number(d.get("messages", 0))}</td>'
            f'<td class="num">{_format_number(d.get("events", 0))}</td>'
            f'<td class="num">{_format_number(d.get("agents", 0))}</td>'
            f'<td class="num">{_format_number(d.get("tokens", 0))}</td>'
            f'<td class="num">{(d.get("efficiency") or 0):.1f}%</td>'
            f'<td class="spark-cell">{_sparkline_svg([d.get("messages", 0)])}</td>'
            f"</tr>"
        )

    return (
        "<table><thead><tr>"
        '<th>Day</th><th class="num">Messages</th><th class="num">Events</th>'
        '<th class="num">Agents</th><th class="num">Tokens</th><th class="num">Efficiency</th>'
        "<th>Trend</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _build_peak_hours_comparison(day_metrics):
    """Build a table showing the busiest hour for each day side by side."""
    if not day_metrics:
        return '<p style="color:var(--muted)">No peak hour data available.</p>'

    rows = []
    for d in day_metrics:
        hours = d.get("busiest_hours") or {}
        if not hours or all(v == 0 for v in hours.values()):
            peak_hour = "—"
            peak_count = "—"
            spark = _sparkline_svg([0] * 24)
        else:
            peak = max(hours.items(), key=lambda item: (item[1], -item[0]))
            peak_hour = f"{peak[0]:02d}:00 UTC"
            peak_count = _format_number(peak[1])
            values = [hours.get(h, 0) for h in range(24)]
            spark = _sparkline_svg(values)

        date = _series_date(d) or f"Day {d['day']}"
        rows.append(
            f"<tr>"
            f"<td>{html_lib.escape(str(date))}</td>"
            f'<td class="num">{html_lib.escape(str(peak_hour))}</td>'
            f'<td class="num">{html_lib.escape(str(peak_count))}</td>'
            f'<td class="spark-cell">{spark}</td>'
            f"</tr>"
        )

    thead = (
        "<tr>"
        "<th>Date</th>"
        '<th class="num">Peak Hour</th>'
        '<th class="num">Messages at Peak</th>'
        '<th class="spark-cell">Hourly Distribution</th>'
        "</tr>"
    )
    return f"<table><thead>{thead}</thead><tbody>{''.join(rows)}</tbody></table>"


def _build_conversation_depth_comparison(day_metrics):
    """Build a table showing conversation depth metrics per day."""
    if not day_metrics:
        return '<p style="color:var(--muted)">No conversation depth data available.</p>'

    rows = []
    for d in day_metrics:
        cd = d.get("conversation_depth") or {}
        if not cd or cd.get("total_chains", 0) == 0:
            total = "—"
            max_d = "—"
            mean_d = "—"
            median_d = "—"
            spark = _sparkline_svg([0])
        else:
            total = _format_number(cd.get("total_chains", 0))
            max_d = _format_number(cd.get("max_depth", 0))
            mean_d = f"{cd.get('mean_depth', 0.0):.1f}"
            median_d = f"{cd.get('median_depth', 0.0):.1f}"
            spark = _sparkline_svg([cd.get("total_chains", 0)])

        date = _series_date(d) or f"Day {d['day']}"
        rows.append(
            f"<tr>"
            f"<td>{html_lib.escape(str(date))}</td>"
            f'<td class="num">{html_lib.escape(str(total))}</td>'
            f'<td class="num">{html_lib.escape(str(max_d))}</td>'
            f'<td class="num">{html_lib.escape(str(mean_d))}</td>'
            f'<td class="num">{html_lib.escape(str(median_d))}</td>'
            f'<td class="spark-cell">{spark}</td>'
            f"</tr>"
        )

    thead = (
        "<tr>"
        "<th>Date</th>"
        '<th class="num">Total Chains</th>'
        '<th class="num">Max Depth</th>'
        '<th class="num">Mean Depth</th>'
        '<th class="num">Median Depth</th>'
        '<th class="spark-cell">Trend</th>'
        "</tr>"
    )
    return f"<table><thead>{thead}</thead><tbody>{''.join(rows)}</tbody></table>"




def _build_response_speed_comparison(day_metrics):
    """Build a table showing response speed metrics per day."""
    if not day_metrics:
        return '<p style="color:var(--muted)">No response speed data available.</p>'

    rows = []
    for d in day_metrics:
        latency_rows = d.get("response_latency") or []
        if not latency_rows:
            median_str = "—"
            total_replies = "—"
            num_agents = "—"
            spark = _sparkline_svg([0])
        else:
            total_replies_val = sum(r.get("responses", 0) for r in latency_rows)
            if total_replies_val > 0:
                weighted = sum(
                    r.get("median_seconds", 0) * r.get("responses", 0)
                    for r in latency_rows
                ) / total_replies_val
            else:
                weighted = 0.0
            median_str = f"{weighted:.1f}s"
            total_replies = _format_number(total_replies_val)
            num_agents = _format_number(len(latency_rows))
            spark = _sparkline_svg([round(weighted, 1)])

        date = _series_date(d) or f"Day {d['day']}"
        rows.append(
            f"<tr>"
            f"<td>{html_lib.escape(str(date))}</td>"
            f'<td class="num">{html_lib.escape(str(median_str))}</td>'
            f'<td class="num">{html_lib.escape(str(total_replies))}</td>'
            f'<td class="num">{html_lib.escape(str(num_agents))}</td>'
            f'<td class="spark-cell">{spark}</td>'
            f"</tr>"
        )

    thead = (
        "<tr>"
        "<th>Date</th>"
        '<th class="num">Median Response</th>'
        '<th class="num">Total Replies</th>'
        '<th class="num">Responding Agents</th>'
        '<th class="spark-cell">Trend</th>'
        "</tr>"
    )
    return f"<table><thead>{thead}</thead><tbody>{''.join(rows)}</tbody></table>"

def _build_agent_leaderboard(day_metrics):
    """Build top agents leaderboard with bar chart."""
    agent_totals = {}
    for d in day_metrics:
        for entry in d.get("top_agents", []):
            agent = entry.get("agent", "Unknown")
            agent_totals[agent] = agent_totals.get(agent, 0) + entry.get("messages", 0)

    sorted_agents = sorted(agent_totals.items(), key=lambda x: x[1], reverse=True)[:10]

    if not sorted_agents:
        return '<p style="color:var(--muted)">No agent data available.</p>'

    rows = []
    for i, (agent, total) in enumerate(sorted_agents):
        rank_cls = f"rank-{i + 1}" if i < 3 else "rank-other"
        rows.append(
            f'<tr><td><span class="rank {rank_cls}">{i + 1}</span>{html_lib.escape(str(agent))}</td>'
            f'<td class="num">{_format_number(total)}</td></tr>'
        )

    chart = _bar_svg([v for _, v in sorted_agents], [a for a, _ in sorted_agents])

    return (
        '<div class="leaderboard-grid">'
        "<div>"
        '<table><thead><tr><th>Agent</th><th class="num">Messages</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
        f'<div style="display:flex;align-items:center;justify-content:center;">{chart}</div>'
        "</div>"
    )


def _build_room_participation(day_metrics):
    """Build room participation bar chart from latest day."""
    if not day_metrics:
        return '<p style="color:var(--muted)">No room data available.</p>'

    latest = day_metrics[-1]
    rooms = latest.get("room_participation", {})
    if not rooms:
        return '<p style="color:var(--muted)">No room data for latest day.</p>'

    labels = list(rooms.keys())
    values = [
        sum(agents.values()) if isinstance(agents, dict) else agents
        for agents in rooms.values()
    ]
    chart = _bar_svg(values, labels)

    return f'<div style="display:flex;align-items:center;justify-content:center;">{chart}</div>'


def _build_daily_trends_table(day_metrics):
    """Build daily trends table from latest 7 days."""
    all_trends = []
    for d in day_metrics:
        all_trends.extend(d.get("daily_trends", []))

    # Take last 7 unique dates
    seen = set()
    rows = []
    for t in reversed(all_trends):
        date = t.get("date", "")
        if date in seen:
            continue
        seen.add(date)
        rows.insert(0, t)
        if len(rows) >= 7:
            break

    if not rows:
        return '<p style="color:var(--muted)">No daily trend data available.</p>'

    trs = []
    for t in rows:
        trs.append(
            f"<tr>"
            f"<td>{html_lib.escape(str(t.get('date', '')))}</td>"
            f'<td class="num">{_format_number(t.get("messages", 0))}</td>'
            f'<td class="num">{_format_number(t.get("events", 0))}</td>'
            f'<td class="num">{_format_number(t.get("active_agents", 0))}</td>'
            f'<td class="num">{_format_number(t.get("total_tokens", 0))}</td>'
            f'<td class="num">{(t.get("efficiency") or 0):.1f}%</td>'
            f"</tr>"
        )

    return (
        "<table><thead><tr>"
        '<th>Date</th><th class="num">Messages</th><th class="num">Events</th>'
        '<th class="num">Agents</th><th class="num">Tokens</th><th class="num">Efficiency</th>'
        "</tr></thead><tbody>" + "".join(trs) + "</tbody></table>"
    )


def _series_date(day_row):
    """Best-effort calendar date for a day_metrics row (from its daily_trends)."""
    dt = day_row.get("daily_trends") or []
    if dt and dt[0].get("date"):
        return dt[0]["date"]
    return None


def _build_room_activity_trends(day_metrics):
    """Per-room message activity across the window as aligned sparklines.

    Builds a sparse {date, messages} series per room, then uses
    analytics.union_dates + densify to zero-fill every room onto one shared,
    sorted date axis so the sparklines are directly comparable.
    """
    room_series = {}
    for d in day_metrics:
        date = _series_date(d)
        if not date:
            continue
        for room, agents in (d.get("room_participation") or {}).items():
            msgs = sum(agents.values()) if isinstance(agents, dict) else (agents or 0)
            room_series.setdefault(room, []).append({"date": date, "messages": msgs})
    if not room_series:
        return '<p style="color:var(--muted)">No room activity data available.</p>'

    axis = analytics.union_dates(*room_series.values())
    rows = []
    for room in sorted(
        room_series, key=lambda r: -sum(x["messages"] for x in room_series[r])
    ):
        dense = analytics.densify(room_series[room], axis, ["messages"])
        values = [r["messages"] for r in dense]
        rows.append(
            f"<tr>"
            f"<td>{html_lib.escape(str(room))}</td>"
            f'<td class="spark-cell">{_sparkline_svg(values)}</td>'
            f'<td class="num">{_format_number(sum(values))}</td>'
            f"</tr>"
        )
    return (
        "<table><thead><tr>"
        '<th>Room</th><th>Trend</th><th class="num">Total Messages</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _build_top_agent_trends(day_metrics, top_n=8):
    """Top agents' per-day message trajectories across the window as sparklines.

    Aggregates each agent's per-day message counts into a sparse series, then
    aligns the most active agents onto one shared axis via union_dates/densify.
    """
    agent_series = {}
    totals = {}
    for d in day_metrics:
        date = _series_date(d)
        if not date:
            continue
        for entry in d.get("top_agents") or []:
            agent = entry.get("agent")
            msgs = entry.get("messages", 0)
            agent_series.setdefault(agent, []).append({"date": date, "messages": msgs})
            totals[agent] = totals.get(agent, 0) + msgs
    if not totals:
        return '<p style="color:var(--muted)">No agent activity data available.</p>'

    top_agents = sorted(totals, key=lambda x: -totals[x])[:top_n]
    axis = analytics.union_dates(*(agent_series[a] for a in top_agents))
    rows = []
    for agent in top_agents:
        dense = analytics.densify(agent_series[agent], axis, ["messages"])
        values = [r["messages"] for r in dense]
        rows.append(
            f"<tr>"
            f"<td>{html_lib.escape(str(agent))}</td>"
            f'<td class="spark-cell">{_sparkline_svg(values)}</td>'
            f'<td class="num">{_format_number(totals[agent])}</td>'
            f"</tr>"
        )
    return (
        "<table><thead><tr>"
        '<th>Agent</th><th>Trend</th><th class="num">Total Messages</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def generate_comparison(day_metrics, output_path, village_day=0):
    output_path = Path(output_path)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    summary = _build_summary_cards(day_metrics)
    comparison = _build_comparison_table(day_metrics)
    peak_hours = _build_peak_hours_comparison(day_metrics)
    conversation_depth = _build_conversation_depth_comparison(day_metrics)
    response_speed = _build_response_speed_comparison(day_metrics)
    leaderboard = _build_agent_leaderboard(day_metrics)
    rooms = _build_room_participation(day_metrics)
    trends = _build_daily_trends_table(day_metrics)
    agent_trends = _build_top_agent_trends(day_metrics)
    room_trends = _build_room_activity_trends(day_metrics)

    title = "Village Pulse -- Multi-Day Comparison"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>Village Pulse -- Multi-Day Comparison</h1>
  <p>Village Day {html_lib.escape(str(village_day))} &nbsp;|&nbsp; Generated {generated_at}</p>
</header>
<div class="container">
  <div class="section">
    <h2>Summary</h2>
    {summary}
  </div>
  <div class="section">
    <h2>Day-by-Day Comparison</h2>
    {comparison}
  </div>
  <div class="section">
    <h2>Peak Hours Comparison</h2>
    {peak_hours}
  </div>
  <div class="section">
    <h2>Conversation Depth Comparison</h2>
    {conversation_depth}
  </div>
  <div class="section">
    <h2>Response Speed Comparison</h2>
    {response_speed}
  </div>
  <div class="section">
    <h2>Agent Leaderboard</h2>
    {leaderboard}
  </div>
  <div class="section">
    <h2>Room Participation (Latest Day)</h2>
    {rooms}
  </div>
  <div class="section">
    <h2>Daily Trends (Last 7 Days)</h2>
    {trends}
  </div>
  <div class="section">
    <h2>Top Agents Over Time</h2>
    {agent_trends}
  </div>
  <div class="section">
    <h2>Room Activity Over Time</h2>
    {room_trends}
  </div>
</div>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    LOG.info("Wrote comparison dashboard to %s", output_path)


def generate_comparison_archive(
    output_dir,
    days_back=DEFAULT_DAYS_BACK,
    endpoint=None,
    village_slug="actual-launch-1",
    village_id=None,
):
    """Fetch multi-day events and generate a comparison dashboard.

    Parameters
    ----------
    output_dir : str | Path
        Directory to write the comparison HTML into.
    days_back : int
        How many past days to include.
    endpoint : str, optional
        Custom API base URL.
    village_slug : str
        Village slug to resolve.
    village_id : str, optional
        Pre-known village UUID.

    Returns
    -------
    Path
        Path to the written comparison HTML file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client_kwargs = {"village_slug": village_slug}
    if endpoint is not None:
        client_kwargs["endpoint"] = endpoint
    if village_id is not None:
        client_kwargs["village_id"] = village_id
    client = api_client.VillageAPIClient(**client_kwargs)

    today = client._discover_latest_day()
    if today is None:
        LOG.warning("Could not discover current village day; falling back to days_back")
        today = days_back
    start_day = max(1, today - days_back + 1)

    day_metrics = []
    for day in range(start_day, today + 1):
        LOG.info("Fetching day %d...", day)
        try:
            events = list(client.iter_raw_events_for_day(day))
        except api_client.APIError as exc:
            LOG.warning("Skipping day %d: %s", day, exc)
            continue

        if not events:
            LOG.info("Day %d has no events, skipping.", day)
            continue

        agents = client.get_agents()
        rooms = client.get_rooms()
        events = [
            api_client._flatten_event(raw, agents=agents, rooms=rooms) for raw in events
        ]

        metrics = analytics.compute_all(events)
        room_part = metrics.get("room_participation", {})
        top = [
            {"agent": a, "messages": c}
            for a, c in metrics.get("messages_per_agent", {}).items()
        ]
        top = sorted(top, key=lambda x: x["messages"], reverse=True)[:10]

        day_metrics.append(
            {
                "day": day,
                "messages": sum(metrics.get("messages_per_agent", {}).values()),
                "events": metrics.get("meta", {}).get("total_events", len(events)),
                "agents": len(metrics.get("messages_per_agent", {})),
                "tokens": metrics.get("token_usage", {})
                .get("totals", {})
                .get("total", 0),
                "efficiency": metrics.get("token_usage", {})
                .get("totals", {})
                .get("efficiency", 0),
                "room_participation": room_part,
                "top_agents": top,
                "daily_trends": metrics.get("daily_trends", []),
                "busiest_hours": metrics.get("busiest_hours", {}),
                "conversation_depth": metrics.get("conversation_depth", {}),
                "response_latency": metrics.get("response_latency", []),
            }
        )

    output_path = output_dir / "comparison.html"
    generate_comparison(day_metrics, output_path, village_day=today)
    return output_path


def main(argv=None):
    """CLI entry point for archive comparison generator."""
    parser = argparse.ArgumentParser(
        description="Generate a multi-day Village Pulse comparison dashboard."
    )
    parser.add_argument(
        "-o", "--output", required=True, help="Output directory for comparison HTML."
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=DEFAULT_DAYS_BACK,
        help=f"Number of past days to compare (default: {DEFAULT_DAYS_BACK}).",
    )
    parser.add_argument("--endpoint", default=None, help="Custom API base URL.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging."
    )
    args = parser.parse_args(argv)

    if args.days_back < 1:
        print(
            "[village-pulse-compare] error: --days-back must be >= 1", file=sys.stderr
        )
        return 1

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        path = generate_comparison_archive(
            output_dir=args.output,
            days_back=args.days_back,
            endpoint=args.endpoint,
        )
        print(f"Comparison dashboard written to: {path}")
        return 0
    except Exception as exc:
        LOG.error("Failed to generate comparison: %s", exc)
        return 1


__all__ = [
    "generate_comparison",
    "generate_comparison_archive",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
