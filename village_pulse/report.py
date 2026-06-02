"""HTML report generation for Village Pulse dashboards.

The report module intentionally accepts a flexible metrics dictionary so it can
integrate with analytics implementations as they evolve. The public entry point
is :func:`generate`, which renders a self-contained single-page HTML dashboard
and writes it to disk.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape


DEFAULT_TITLE = "Village Pulse Dashboard"


_DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #64748b;
      --line: #d9e2ef;
      --accent: #2f6fed;
      --accent-soft: #e8f0ff;
      --good: #17803d;
      --warn: #b7791f;
      --token: #7c3aed;
      --shadow: 0 12px 28px rgba(23, 32, 51, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at top left, #e8f0ff 0, transparent 34rem), var(--bg);
      color: var(--ink);
      line-height: 1.5;
    }
    header {
      padding: 2.5rem clamp(1rem, 4vw, 4rem) 1.5rem;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.78);
      backdrop-filter: blur(8px);
    }
    h1 { margin: 0 0 .4rem; font-size: clamp(2rem, 4vw, 3.4rem); letter-spacing: -0.04em; }
    h2 { margin: 0 0 1rem; font-size: 1.2rem; }
    h3 { margin: 1.2rem 0 .5rem; font-size: 1rem; }
    .subtitle { color: var(--muted); max-width: 70rem; }
    main { padding: 1.5rem clamp(1rem, 4vw, 4rem) 3rem; }
    .meta { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: 1rem; }
    .pill {
      display: inline-flex; align-items: center; gap: .3rem;
      border: 1px solid var(--line); background: var(--panel); color: var(--muted);
      border-radius: 999px; padding: .35rem .7rem; font-size: .9rem;
    }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 1rem; margin: 1rem 0 1.5rem; }
    .card {
      background: var(--panel); border: 1px solid var(--line); border-radius: 1rem;
      box-shadow: var(--shadow); padding: 1.1rem;
    }
    .stat-label { color: var(--muted); font-size: .88rem; text-transform: uppercase; letter-spacing: .06em; }
    .stat-value { margin-top: .25rem; font-size: 2rem; font-weight: 750; letter-spacing: -0.03em; }
    .section { margin-top: 1.2rem; }
    table { width: 100%; border-collapse: collapse; font-size: .95rem; }
    th, td { padding: .65rem .55rem; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; background: #fbfdff; }
    tr:last-child td { border-bottom: 0; }
    .bar-cell { min-width: 8rem; }
    .bar-track { height: .55rem; border-radius: 999px; background: #edf2f7; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--accent), #59a6ff); }
    .token-fill { background: linear-gradient(90deg, var(--token), #a78bfa); }
    .chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: 1rem; }
    .trend-chart { border: 1px solid var(--line); border-radius: .85rem; padding: .9rem; background: #fbfdff; }
    .chart-head { display: flex; justify-content: space-between; gap: .8rem; align-items: baseline; margin-bottom: .55rem; }
    .chart-title { font-weight: 700; }
    .chart-value { color: var(--muted); font-size: .9rem; }
    .sparkline { width: 100%; height: 8.5rem; overflow: visible; }
    .spark-grid { stroke: var(--line); stroke-width: .45; }
    .spark-area { opacity: .14; }
    .spark-line { fill: none; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
    .spark-dot { stroke: var(--panel); stroke-width: 1; }
    .chart-dates { display: flex; justify-content: space-between; color: var(--muted); font-size: .78rem; margin-top: .3rem; }
    .muted { color: var(--muted); }
    .heatmap { display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; margin-top: .6rem; }
    .heat-cell { aspect-ratio: 1 / 1; border-radius: 4px; border: 1px solid var(--line); display: flex; align-items: center; justify-content: center; font-size: .62rem; color: #1f2937; }
    .heat-l0 { background: #f1f5f9; color: var(--muted); }
    .heat-l1 { background: #dbeafe; }
    .heat-l2 { background: #93c5fd; }
    .heat-l3 { background: #3b82f6; color: #fff; }
    .heat-l4 { background: #1d4ed8; color: #fff; }
    .heat-axis { display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; margin-top: .25rem; color: var(--muted); font-size: .58rem; text-align: center; }
    .good { color: var(--good); font-weight: 650; }
    .warn { color: var(--warn); font-weight: 650; }
    pre {
      overflow: auto; max-height: 26rem; padding: 1rem; border-radius: .75rem;
      background: #0f172a; color: #e2e8f0; font-size: .85rem;
    }
    footer { margin-top: 2rem; color: var(--muted); font-size: .9rem; }
  </style>
</head>
<body>
  <header>
    <h1>{{ title }}</h1>
    <p class="subtitle">A concise activity snapshot for AI Village rooms, agents, and message trends.</p>
    <div class="meta">
      <span class="pill">Generated {{ generated_at }}</span>
      {% if context.room %}<span class="pill">Room: {{ context.room }}</span>{% else %}<span class="pill">All rooms</span>{% endif %}
      {% if context.days %}<span class="pill">Window: {{ context.days }} day{{ '' if context.days == 1 else 's' }}</span>{% endif %}
      {% if context.agent %}<span class="pill">Agent: {{ context.agent }}</span>{% endif %}
      {% if context.version %}<span class="pill">v{{ context.version }}</span>{% endif %}
    </div>
  </header>
  <main>
    <section class="grid" aria-label="summary metrics">
      {% for card in summary_cards %}
      <article class="card">
        <div class="stat-label">{{ card.label }}</div>
        <div class="stat-value">{{ card.value }}</div>
        {% if card.note %}<div class="muted">{{ card.note }}</div>{% endif %}
      </article>
      {% endfor %}
    </section>

    {% if days > 1 and trend_charts %}
    <section class="section card">
      <h2>Activity digest trend ({{ days }} days)</h2>
      <p class="muted" style="margin-top: 0;">Daily message volume trend across the active days in the digest period.</p>
      {% for chart in trend_charts if chart.title == 'Messages over time' %}
      <div style="border: 1px solid var(--line); border-radius: .85rem; padding: 1rem; background: #fbfdff; margin-top: 0.5rem;">
        <div class="chart-head"><span class="chart-title">{{ chart.title }} (Daily sparkline)</span><span class="chart-value">Peak {{ chart.peak }} messages</span></div>
        <svg class="sparkline" viewBox="0 0 100 44" role="img" aria-label="{{ chart.title }} trend from {{ chart.start_date }} to {{ chart.end_date }}" preserveAspectRatio="none" style="height: 5rem;">
          <line class="spark-grid" x1="0" y1="38" x2="100" y2="38"></line>
          <line class="spark-grid" x1="0" y1="22" x2="100" y2="22"></line>
          <line class="spark-grid" x1="0" y1="6" x2="100" y2="6"></line>
          <polygon class="spark-area" fill="{{ chart.color }}" points="{{ chart.area_points }}"></polygon>
          <polyline class="spark-line" stroke="{{ chart.color }}" points="{{ chart.points }}"></polyline>
          {% for point in chart.point_rows %}<circle class="spark-dot" fill="{{ chart.color }}" cx="{{ point.x }}" cy="{{ point.y }}" r="1.6"><title>{{ point.date }}: {{ point.value }}</title></circle>{% endfor %}
        </svg>
        <div class="chart-dates"><span>{{ chart.start_date }}</span><span>{{ chart.end_date }}</span></div>
      </div>
      {% endfor %}
    </section>
    {% endif %}

    <section class="section card">
      <h2>Agent activity{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
      {% if agent_rows %}
      <table>
        <thead><tr><th>Agent</th><th>Messages</th><th class="bar-cell">Share</th></tr></thead>
        <tbody>
          {% for row in agent_rows %}
          <tr>
            <td>{{ row.name }}</td>
            <td>{{ row.count }}</td>
            <td class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width: {{ row.percent }}%"></div></div><span class="muted">{{ row.percent }}%</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}<p class="muted">No per-agent message metrics were provided.</p>{% endif %}
    </section>

    <section class="section card">
      <h2>Room participation{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
      {% if room_rows %}
      <table>
        <thead><tr><th>Room</th><th>Messages</th><th>Agents</th><th>Participation</th></tr></thead>
        <tbody>
          {% for row in room_rows %}
          <tr><td>{{ row.room }}</td><td>{{ row.messages }}</td><td>{{ row.agents }}</td><td>{{ row.participation }}</td></tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}<p class="muted">No room participation metrics were provided.</p>{% endif %}
    </section>

    <section class="grid section" aria-label="trend details">
      <article class="card">
        <h2>Busiest hours{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
        {% if busiest_hours %}
        <table><thead><tr><th>Hour</th><th>Messages</th></tr></thead><tbody>
          {% for hour in busiest_hours %}<tr><td>{{ hour.hour }}</td><td>{{ hour.count }}</td></tr>{% endfor %}
        </tbody></table>
        {% else %}<p class="muted">No hourly activity metrics were provided.</p>{% endif %}
      </article>
      <article class="card">
        <h2>Agent status{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
        <p><span class="good">Active:</span> {{ active_agents|join(', ') if active_agents else 'none listed' }}</p>
        <p><span class="warn">Inactive:</span> {{ inactive_agents|join(', ') if inactive_agents else 'none listed' }}</p>
      </article>
    </section>

    <section class="section card">
      <h2>Activity heatmap{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
      {% if heatmap_cells %}
      <p class="muted">Messages by hour of day (UTC). Darker cells indicate busier hours.</p>
      <div class="heatmap" role="img" aria-label="Message activity by UTC hour of day">
        {% for cell in heatmap_cells %}<div class="heat-cell heat-l{{ cell.level }}" title="{{ cell.hour }}:00 UTC — {{ cell.count }} messages">{{ cell.count }}</div>{% endfor %}
      </div>
      <div class="heat-axis">
        {% for cell in heatmap_cells %}<span>{{ cell.hour }}</span>{% endfor %}
      </div>
      {% else %}<p class="muted">No hourly activity metrics were provided.</p>{% endif %}
    </section>

    <section class="section card">
      <h2>Trends over time{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
      {% if trend_charts %}
      <div class="chart-grid">
        {% for chart in trend_charts %}
        <article class="trend-chart">
          <div class="chart-head"><span class="chart-title">{{ chart.title }}</span><span class="chart-value">Peak {{ chart.peak }}</span></div>
          <svg class="sparkline" viewBox="0 0 100 44" role="img" aria-label="{{ chart.title }} trend from {{ chart.start_date }} to {{ chart.end_date }}" preserveAspectRatio="none">
            <title>{{ chart.title }} trend</title>
            <desc>Daily {{ chart.title|lower }} values from {{ chart.start_date }} to {{ chart.end_date }} with a peak of {{ chart.peak }}.</desc>
            <line class="spark-grid" x1="0" y1="38" x2="100" y2="38"></line>
            <line class="spark-grid" x1="0" y1="22" x2="100" y2="22"></line>
            <line class="spark-grid" x1="0" y1="6" x2="100" y2="6"></line>
            <polygon class="spark-area" fill="{{ chart.color }}" points="{{ chart.area_points }}"></polygon>
            <polyline class="spark-line" stroke="{{ chart.color }}" points="{{ chart.points }}"></polyline>
            {% for point in chart.point_rows %}<circle class="spark-dot" fill="{{ chart.color }}" cx="{{ point.x }}" cy="{{ point.y }}" r="1.6"><title>{{ point.date }}: {{ point.value }}</title></circle>{% endfor %}
          </svg>
          <div class="chart-dates"><span>{{ chart.start_date }}</span><span>{{ chart.end_date }}</span></div>
        </article>
        {% endfor %}
      </div>
      {% else %}<p class="muted">No trend chart metrics were provided.</p>{% endif %}
    </section>

    <section class="section card">
      <h2>Top agent trends{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
      {% if agent_trend_charts %}
      <div class="chart-grid">
        {% for chart in agent_trend_charts %}
        <article class="trend-chart">
          <div class="chart-head"><span class="chart-title">{{ chart.agent }}</span><span class="chart-value">{{ chart.total_messages }} messages</span></div>
          <svg class="sparkline" viewBox="0 0 100 44" role="img" aria-label="{{ chart.agent }} message trend from {{ chart.start_date }} to {{ chart.end_date }}" preserveAspectRatio="none">
            <title>{{ chart.agent }} message trend</title>
            <desc>Daily message counts for {{ chart.agent }} from {{ chart.start_date }} to {{ chart.end_date }} with a peak of {{ chart.peak }} messages and {{ chart.total_tokens }} tokens.</desc>
            <line class="spark-grid" x1="0" y1="38" x2="100" y2="38"></line>
            <line class="spark-grid" x1="0" y1="22" x2="100" y2="22"></line>
            <line class="spark-grid" x1="0" y1="6" x2="100" y2="6"></line>
            <polygon class="spark-area" fill="{{ chart.color }}" points="{{ chart.area_points }}"></polygon>
            <polyline class="spark-line" stroke="{{ chart.color }}" points="{{ chart.points }}"></polyline>
            {% for point in chart.point_rows %}<circle class="spark-dot" fill="{{ chart.color }}" cx="{{ point.x }}" cy="{{ point.y }}" r="1.6"><title>{{ point.date }}: {{ point.value }} messages</title></circle>{% endfor %}
          </svg>
          <div class="chart-dates"><span>{{ chart.start_date }}</span><span>Peak {{ chart.peak }} · {{ chart.total_tokens }} tokens</span><span>{{ chart.end_date }}</span></div>
        </article>
        {% endfor %}
      </div>
      {% else %}<p class="muted">No per-agent trend metrics were provided.</p>{% endif %}
    </section>

    <section class="section card">
      <h2>Daily trends{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
      {% if daily_trend_rows %}
      <table>
        <thead><tr><th>Date</th><th>Messages</th><th>Events</th><th>Active agents</th><th>Total tokens</th><th>Input:output</th></tr></thead>
        <tbody>
          {% for row in daily_trend_rows %}
          <tr><td>{{ row.date }}</td><td>{{ row.messages }}</td><td>{{ row.events }}</td><td>{{ row.active_agents }}</td><td>{{ row.total_tokens }}</td><td>{{ row.efficiency }}</td></tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}<p class="muted">No daily trend metrics were provided.</p>{% endif %}
    </section>

    <section class="section card">
      <h2>Token usage{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
      {% if token_summary %}
      <div class="grid" aria-label="token summary metrics">
        {% for card in token_summary %}
        <article>
          <div class="stat-label">{{ card.label }}</div>
          <div class="stat-value">{{ card.value }}</div>
          {% if card.note %}<div class="muted">{{ card.note }}</div>{% endif %}
        </article>
        {% endfor %}
      </div>
      {% if token_agent_rows %}
      <h3>Top agents by tokens</h3>
      <table>
        <thead><tr><th>Agent</th><th>Total</th><th>Input</th><th>Output</th><th>Input:output</th><th class="bar-cell">Share</th></tr></thead>
        <tbody>
          {% for row in token_agent_rows %}
          <tr>
            <td>{{ row.name }}</td><td>{{ row.total }}</td><td>{{ row.input }}</td><td>{{ row.output }}</td><td>{{ row.efficiency }}</td>
            <td class="bar-cell"><div class="bar-track"><div class="bar-fill token-fill" style="width: {{ row.percent }}%"></div></div><span class="muted">{{ row.percent }}%</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% endif %}
      {% if token_room_rows %}
      <h3>Rooms by tokens</h3>
      <table>
        <thead><tr><th>Room</th><th>Total</th><th>Input</th><th>Output</th><th>Input:output</th></tr></thead>
        <tbody>
          {% for row in token_room_rows %}<tr><td>{{ row.name }}</td><td>{{ row.total }}</td><td>{{ row.input }}</td><td>{{ row.output }}</td><td>{{ row.efficiency }}</td></tr>{% endfor %}
        </tbody>
      </table>
      {% endif %}
      {% else %}<p class="muted">No token usage metrics were provided.</p>{% endif %}
    </section>

    <section class="section card">
      <h2>Agent interactions{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
      <p class="muted">Reply-adjacency analysis showing who responds to whom (within a 30-minute window) and overall reply activity.</p>
      
      {% if interaction_graph_rows or interaction_rankings.top_responders or interaction_rankings.top_targets %}
      <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr)); gap: 1.5rem; margin-top: 1rem;">
        
        <article class="card" style="box-shadow: none; border: 1px solid var(--line); padding: 1rem;">
          <h3 style="margin-top: 0;">Reply networks</h3>
          {% if interaction_graph_rows %}
          <div style="display: flex; flex-direction: column; gap: 1rem;">
            {% for row in interaction_graph_rows %}
            <div>
              <strong style="font-size: 0.95rem;">{{ row.responder }}</strong> <span class="muted">replied to:</span>
              <table style="margin-top: 0.25rem; font-size: 0.9rem;">
                <tbody>
                  {% for target in row.targets %}
                  <tr>
                    <td style="width: 45%; padding: 0.25rem 0;">{{ target.name }}</td>
                    <td style="width: 15%; padding: 0.25rem 0; text-align: right; font-weight: 600;">{{ target.count }}</td>
                    <td class="bar-cell" style="padding: 0.25rem 0 0.25rem 0.5rem;">
                      <div class="bar-track" style="height: 0.45rem;"><div class="bar-fill" style="width: {{ target.percent }}%"></div></div>
                    </td>
                  </tr>
                  {% endfor %}
                </tbody>
              </table>
            </div>
            {% endfor %}
          </div>
          {% else %}
          <p class="muted">No direct agent-to-agent replies detected in the window.</p>
          {% endif %}
        </article>

        <article class="card" style="box-shadow: none; border: 1px solid var(--line); padding: 1rem; display: flex; flex-direction: column; gap: 1.5rem;">
          <div>
            <h3 style="margin-top: 0;">Top responders <span class="muted" style="font-size: 0.8rem; font-weight: normal;">(replies made)</span></h3>
            {% if interaction_rankings.top_responders %}
            <table>
              <thead><tr><th>Agent</th><th style="text-align: right;">Replies</th></tr></thead>
              <tbody>
                {% for row in interaction_rankings.top_responders %}
                <tr><td>{{ row.agent }}</td><td style="text-align: right; font-weight: 600;">{{ row.count }}</td></tr>
                {% endfor %}
              </tbody>
            </table>
            {% else %}
            <p class="muted">No replies made.</p>
            {% endif %}
          </div>

          <div>
            <h3 style="margin-top: 0;">Top targets <span class="muted" style="font-size: 0.8rem; font-weight: normal;">(replies received)</span></h3>
            {% if interaction_rankings.top_targets %}
            <table>
              <thead><tr><th>Agent</th><th style="text-align: right;">Replies</th></tr></thead>
              <tbody>
                {% for row in interaction_rankings.top_targets %}
                <tr><td>{{ row.agent }}</td><td style="text-align: right; font-weight: 600;">{{ row.count }}</td></tr>
                {% endfor %}
              </tbody>
            </table>
            {% else %}
            <p class="muted">No replies received.</p>
            {% endif %}
          </div>
        </article>

      </div>
      {% else %}
      <p class="muted">No interaction network metrics were provided.</p>
      {% endif %}
    </section>

    <section class="section card">
      <h2>Response speed{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
      <p class="muted">Median seconds each agent takes to reply to another agent in the same room (fastest first).</p>
      {% if response_latency %}
      <table>
        <thead><tr><th>Agent</th><th style="text-align: right;">Median response</th><th style="text-align: right;">Replies</th></tr></thead>
        <tbody>
          {% for row in response_latency %}
          <tr><td>{{ row.agent }}</td><td style="text-align: right; font-weight: 600;">{{ row.median_seconds }}s</td><td style="text-align: right;">{{ row.responses }}</td></tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <p class="muted">No agent-to-agent responses detected in the window.</p>
      {% endif %}
    </section>

    <section class="section card">
      <h2>Raw metrics payload{% if days > 1 %} ({{ days }}-Day Digest){% endif %}</h2>
      <p class="muted">Included for transparent debugging while the analytics schema stabilizes.</p>
      <pre>{{ raw_metrics_json }}</pre>
    </section>

    <footer>Generated by Village Pulse. This report is static HTML and can be shared without a running server.</footer>
  </main>
</body>
</html>
"""


def generate(
    metrics: Mapping[str, Any] | None,
    output_path: str | Path,
    context: Mapping[str, Any] | None = None,
) -> Path:
    """Render a self-contained HTML dashboard and write it to ``output_path``.

    Args:
        metrics: Analytics output from ``village_pulse.analytics.compute_all``.
            The function accepts both the expected Village Pulse metric names and
            reasonable aliases so early integration remains smooth.
        output_path: File path where the HTML report should be written.
        context: Optional run metadata such as ``room``, ``days``, ``agent``, and
            package ``version`` from the CLI.

    Returns:
        The resolved :class:`~pathlib.Path` to the written report.
    """

    metrics_dict = dict(metrics or {})
    context_dict = dict(context or {})
    rendered = render(metrics_dict, context_dict)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    return destination.resolve()


def render(
    metrics: Mapping[str, Any] | None, context: Mapping[str, Any] | None = None
) -> str:
    """Return dashboard HTML for ``metrics`` without writing a file."""

    metrics_dict = dict(metrics or {})
    context_dict = dict(context or {})
    view = _build_view_model(metrics_dict, context_dict)
    environment = Environment(autoescape=select_autoescape(("html", "xml")))
    template = environment.from_string(_DASHBOARD_TEMPLATE)
    return template.render(**view)


def _build_view_model(
    metrics: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    meta = metrics.get("meta") if isinstance(metrics.get("meta"), Mapping) else {}
    days = _safe_int(context.get("days"))
    if not days and isinstance(meta, Mapping):
        days = _safe_int(meta.get("days"))

    if days > 1:
        default_title = f"Village Pulse - {days}-Day Digest"
    else:
        default_title = DEFAULT_TITLE

    room_val = context.get("room")
    if room_val and not context.get("title"):
        room_str = str(room_val)
        if not room_str.startswith("#"):
            room_str = "#" + room_str
        day_val = context.get("day")
        if day_val is not None:
            default_title = f"Village Pulse — Day {day_val} — {room_str}"
        elif days > 1:
            default_title = f"{default_title} — {room_str}"
        else:
            default_title = f"Village Pulse — {room_str}"
    total_messages = _first_number(
        metrics, "total_messages", "message_count", "events", default=None
    )
    if total_messages is None and isinstance(meta, Mapping):
        total_messages = _safe_int(
            meta.get("total_messages") or meta.get("total_events")
        )
    agent_counts = _mapping(
        metrics, "messages_per_agent", "agent_message_counts", "agents"
    )

    room_metrics = _mapping(
        metrics, "room_health", "room_participation", "rooms", "participation_by_room"
    )
    active_agents, inactive_agents = _agent_status_lists(
        metrics.get("active_agents") or metrics.get("active"),
        metrics.get("inactive_agents") or metrics.get("inactive"),
    )
    busiest_hours = _hour_rows(
        metrics.get("busiest_hours") or metrics.get("messages_by_hour")
    )
    heatmap_cells = _heatmap_cells(metrics.get("hourly_activity_heatmap"))
    trend = _mapping(metrics, "message_trend", "messages_per_day", "daily_messages")

    token_usage = (
        metrics.get("token_usage")
        if isinstance(metrics.get("token_usage"), Mapping)
        else {}
    )
    token_summary = _token_summary(token_usage, meta)
    token_agent_rows = _token_rows(
        token_usage.get("per_agent") if isinstance(token_usage, Mapping) else None
    )
    token_room_rows = _token_rows(
        token_usage.get("per_room") if isinstance(token_usage, Mapping) else None
    )
    daily_trend_values = _daily_trend_values(metrics.get("daily_trends"))
    daily_trend_rows = _daily_trend_rows(daily_trend_values)
    trend_charts = _trend_charts(daily_trend_values)
    agent_trend_charts = _agent_trend_charts(metrics.get("top_agents_over_time"))
    interaction_graph_rows = _interaction_graph_rows(metrics.get("interaction_graph"))
    interaction_rankings = _interaction_rankings(metrics.get("interaction_rankings"))
    response_latency = _response_latency_rows(metrics.get("response_latency"))

    summary_cards = [
        {
            "label": "Messages",
            "value": total_messages,
            "note": "events included in this report",
        },
        {
            "label": "Active agents",
            "value": len(active_agents)
            if active_agents
            else _safe_int(meta.get("unique_agents")) or len(agent_counts),
            "note": "agents with recent activity",
        },
        {
            "label": "Rooms",
            "value": _safe_int(meta.get("unique_rooms")) or len(room_metrics),
            "note": "rooms represented in analytics",
        },
        {
            "label": "Trend points",
            "value": len(trend),
            "note": "daily/hourly buckets supplied",
        },
    ]

    return {
        "title": html.escape(str(context.get("title") or default_title)),
        "days": days,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "context": context,
        "summary_cards": summary_cards,
        "agent_rows": _agent_rows(agent_counts),
        "room_rows": _room_rows(room_metrics),
        "busiest_hours": busiest_hours,
        "heatmap_cells": heatmap_cells,
        "token_summary": token_summary,
        "token_agent_rows": token_agent_rows,
        "token_room_rows": token_room_rows,
        "daily_trend_rows": daily_trend_rows,
        "trend_charts": trend_charts,
        "agent_trend_charts": agent_trend_charts,
        "interaction_graph_rows": interaction_graph_rows,
        "interaction_rankings": interaction_rankings,
        "response_latency": response_latency,
        "active_agents": active_agents,
        "inactive_agents": inactive_agents,
        "raw_metrics_json": json.dumps(metrics, indent=2, sort_keys=True, default=str),
    }


def _daily_trend_values(values: Any, *, limit: int = 14) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    rows: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        date = value.get("date")
        if not date:
            continue
        rows.append(
            {
                "date": str(date),
                "messages": _safe_int(value.get("messages")),
                "events": _safe_int(value.get("events")),
                "active_agents": _safe_int(value.get("active_agents")),
                "total_tokens": _safe_int(value.get("total_tokens")),
                "efficiency": value.get("efficiency"),
            }
        )
    return rows[-limit:]


def _daily_trend_rows(values: Any) -> list[dict[str, Any]]:
    rows = (
        _daily_trend_values(values)
        if not _is_daily_trend_value_list(values)
        else list(values)
    )
    return [
        {
            "date": str(row["date"]),
            "messages": _format_number(row.get("messages")),
            "events": _format_number(row.get("events")),
            "active_agents": _format_number(row.get("active_agents")),
            "total_tokens": _format_number(row.get("total_tokens")),
            "efficiency": _format_efficiency(row.get("efficiency")),
        }
        for row in rows
    ]


def _trend_charts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    specs = [
        ("Messages over time", "messages", "#2f6fed"),
        ("Tokens over time", "total_tokens", "#7c3aed"),
        ("Active agents over time", "active_agents", "#17803d"),
    ]
    charts: list[dict[str, Any]] = []
    for title, key, color in specs:
        point_rows = _sparkline_points(rows, key)
        points = " ".join(f"{point['x']},{point['y']}" for point in point_rows)
        area_points = f"0,38 {points} 100,38"
        values = [_safe_int(row.get(key)) for row in rows]
        charts.append(
            {
                "title": title,
                "color": color,
                "points": points,
                "area_points": area_points,
                "point_rows": point_rows,
                "peak": _format_number(max(values, default=0)),
                "start_date": str(rows[0].get("date", "—")),
                "end_date": str(rows[-1].get("date", "—")),
            }
        )
    return charts


def _sparkline_points(
    rows: Sequence[Mapping[str, Any]], key: str
) -> list[dict[str, Any]]:
    values = [_safe_int(row.get(key)) for row in rows]
    if not values:
        return []
    high = max(values) or 1
    denominator = max(len(values) - 1, 1)
    points: list[dict[str, Any]] = []
    for index, (row, value) in enumerate(zip(rows, values, strict=False)):
        x = 50.0 if len(values) == 1 else (index / denominator) * 100
        y = 38 - ((value / high) * 32)
        points.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "date": str(row.get("date", "—")),
                "value": _format_number(value),
            }
        )
    return points


def _agent_trend_charts(values: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    palette = ["#2f6fed", "#7c3aed", "#17803d", "#b7791f", "#e11d48"]
    charts: list[dict[str, Any]] = []
    for entry in values:
        if len(charts) >= limit:
            break
        if not isinstance(entry, Mapping):
            continue
        agent = entry.get("agent")
        daily = entry.get("daily")
        if (
            not agent
            or not isinstance(daily, Sequence)
            or isinstance(daily, (str, bytes, bytearray))
        ):
            continue
        rows = _agent_daily_rows(daily)
        point_rows = _sparkline_points(rows, "messages")
        if not point_rows:
            continue
        points = " ".join(f"{point['x']},{point['y']}" for point in point_rows)
        total_messages = _safe_int(entry.get("total_messages")) or sum(
            row["messages"] for row in rows
        )
        total_tokens = sum(row["input_tokens"] + row["output_tokens"] for row in rows)
        color = palette[len(charts) % len(palette)]
        charts.append(
            {
                "agent": str(agent),
                "color": color,
                "points": points,
                "area_points": f"0,38 {points} 100,38",
                "point_rows": point_rows,
                "peak": _format_number(
                    max((row["messages"] for row in rows), default=0)
                ),
                "total_messages": _format_number(total_messages),
                "total_tokens": _format_number(total_tokens),
                "start_date": str(rows[0].get("date", "—")),
                "end_date": str(rows[-1].get("date", "—")),
            }
        )
    return charts


def _agent_daily_rows(values: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping) or not value.get("date"):
            continue
        rows.append(
            {
                "date": str(value.get("date")),
                "messages": _safe_int(value.get("messages")),
                "input_tokens": _safe_int(value.get("input_tokens")),
                "output_tokens": _safe_int(value.get("output_tokens")),
            }
        )
    return rows


def _is_daily_trend_value_list(values: Any) -> bool:
    return (
        isinstance(values, Sequence)
        and not isinstance(values, (str, bytes, bytearray))
        and all(isinstance(value, Mapping) and "date" in value for value in values)
    )


def _token_summary(token_usage: Any, meta: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(token_usage, Mapping):
        return []
    totals = (
        token_usage.get("totals")
        if isinstance(token_usage.get("totals"), Mapping)
        else {}
    )
    input_tokens = _safe_int(totals.get("input") or meta.get("total_input_tokens"))
    output_tokens = _safe_int(totals.get("output") or meta.get("total_output_tokens"))
    total_tokens = _safe_int(totals.get("total")) or input_tokens + output_tokens
    events_with_tokens = _safe_int(totals.get("events_with_tokens"))
    efficiency = _format_efficiency(totals.get("efficiency"))
    if total_tokens == 0 and events_with_tokens == 0 and efficiency == "—":
        return []
    return [
        {
            "label": "Total tokens",
            "value": _format_number(total_tokens),
            "note": "input + output tokens",
        },
        {
            "label": "Input tokens",
            "value": _format_number(input_tokens),
            "note": "prompt/context volume",
        },
        {
            "label": "Output tokens",
            "value": _format_number(output_tokens),
            "note": "generated response volume",
        },
        {
            "label": "Input:output",
            "value": efficiency,
            "note": f"{events_with_tokens} events with token data",
        },
    ]


def _token_rows(values: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    if not isinstance(values, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for name, value in values.items():
        if not isinstance(value, Mapping):
            continue
        input_tokens = _safe_int(value.get("input"))
        output_tokens = _safe_int(value.get("output"))
        total = _safe_int(value.get("total")) or input_tokens + output_tokens
        rows.append(
            {
                "name": str(name),
                "input_raw": input_tokens,
                "output_raw": output_tokens,
                "total_raw": total,
                "input": _format_number(input_tokens),
                "output": _format_number(output_tokens),
                "total": _format_number(total),
                "efficiency": _format_efficiency(value.get("efficiency")),
            }
        )
    rows.sort(key=lambda row: (-row["total_raw"], row["name"].lower()))
    max_total = max((row["total_raw"] for row in rows), default=1) or 1
    for row in rows:
        row["percent"] = round((row["total_raw"] / max_total) * 100, 1)
    return rows[:limit]


def _format_efficiency(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.1f}:1"


def _format_number(value: Any) -> str:
    return f"{_safe_int(value):,}"


def _first_number(
    metrics: Mapping[str, Any], *keys: str, default: int | None = 0
) -> int | None:
    for key in keys:
        if key in metrics:
            value = metrics[key]
            if isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                return len(value)
            return _safe_int(value)
    return default


def _mapping(metrics: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = metrics.get(key)
        if isinstance(value, Mapping):
            return {str(k): v for k, v in value.items()}
    return {}


def _agent_rows(agent_counts: Mapping[str, Any]) -> list[dict[str, Any]]:
    counts = {name: _safe_int(count) for name, count in agent_counts.items()}
    total = max(sum(counts.values()), 1)
    rows = [
        {"name": name, "count": count, "percent": round((count / total) * 100, 1)}
        for name, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0].lower())
        )
    ]
    return rows


def _room_rows(room_metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for room, value in sorted(room_metrics.items(), key=lambda item: item[0].lower()):
        if isinstance(value, Mapping):
            messages = _safe_int(
                value.get("messages")
                or value.get("message_count")
                or value.get("count")
            )
            if (
                messages == 0
                and value
                and all(_looks_numeric(v) for v in value.values())
            ):
                messages = sum(_safe_int(v) for v in value.values())
            agents_value = value.get("agents") or value.get("active_agents")
            if (
                agents_value is None
                and value
                and all(_looks_numeric(v) for v in value.values())
            ):
                agents = len(value)
            elif isinstance(agents_value, Sequence) and not isinstance(
                agents_value, (str, bytes, bytearray)
            ):
                agents = len(agents_value)
            else:
                agents = _safe_int(agents_value)
            participation = (
                value.get("participation_rate") or value.get("participation") or "—"
            )
        else:
            messages = _safe_int(value)
            agents = "—"
            participation = "—"
        rows.append(
            {
                "room": room,
                "messages": messages,
                "agents": agents,
                "participation": participation,
            }
        )
    return rows


def _hour_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        items = value.items()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = []
        rows: list[dict[str, Any]] = []
        for entry in value:
            if isinstance(entry, Mapping):
                rows.append(
                    {
                        "hour": entry.get("hour", "—"),
                        "count": _safe_int(entry.get("count") or entry.get("messages")),
                    }
                )
            elif (
                isinstance(entry, Sequence)
                and len(entry) >= 2
                and not isinstance(entry, (str, bytes, bytearray))
            ):
                rows.append({"hour": entry[0], "count": _safe_int(entry[1])})
        return rows
    else:
        return []
    return [
        {"hour": key, "count": _safe_int(count)}
        for key, count in sorted(items, key=lambda item: str(item[0]))
    ]


def _heatmap_cells(value: Any) -> list[dict[str, Any]]:
    """Build 24 hour-of-day cells from ``hourly_activity_heatmap``.

    Accepts a 24-element sequence of counts (the canonical
    :func:`analytics.hourly_activity_heatmap` output) or a ``{hour: count}``
    mapping. Each cell carries its ``hour``, ``count`` and a 0-4 ``level``
    bucket (relative to the peak hour) used purely for CSS shading.
    """
    counts = [0] * 24
    if isinstance(value, Mapping):
        for key, count in value.items():
            hour = _safe_int(key)
            if hour is not None and 0 <= hour < 24:
                counts[hour] = _safe_int(count) or 0
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for hour, count in enumerate(value):
            if hour >= 24:
                break
            counts[hour] = _safe_int(count) or 0
    else:
        return []
    peak = max(counts) if counts else 0
    cells: list[dict[str, Any]] = []
    for hour, count in enumerate(counts):
        if peak <= 0 or count <= 0:
            level = 0
        else:
            level = max(1, min(4, round(count / peak * 4)))
        cells.append({"hour": hour, "count": count, "level": level})
    return cells


def _agent_status_lists(
    active_value: Any, inactive_value: Any = None
) -> tuple[list[str], list[str]]:
    if isinstance(active_value, Mapping) and (
        "active" in active_value or "inactive" in active_value
    ):
        return _string_list(active_value.get("active")), _string_list(
            active_value.get("inactive")
        )
    return _string_list(active_value), _string_list(inactive_value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [str(key) for key in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item) for item in value]
    return [str(value)]


def _looks_numeric(value: Any) -> bool:
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _interaction_graph_rows(graph: Any) -> list[dict[str, Any]]:
    if not isinstance(graph, Mapping):
        return []
    max_count = 1
    for responder, targets in graph.items():
        if isinstance(targets, Mapping):
            for count in targets.values():
                max_count = max(max_count, _safe_int(count))

    rows = []
    for responder, targets in sorted(graph.items(), key=lambda kv: str(kv[0]).lower()):
        if not isinstance(targets, Mapping) or not targets:
            continue
        formatted_targets = []
        for target, count in targets.items():
            cnt = _safe_int(count)
            percent = round((cnt / max_count) * 100, 1) if max_count > 0 else 0
            formatted_targets.append(
                {"name": str(target), "count": cnt, "percent": percent}
            )
        rows.append({"responder": str(responder), "targets": formatted_targets})
    return rows


def _response_latency_rows(value: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    """Coerce analytics.response_latency output into safe table rows."""
    rows: list[dict[str, Any]] = []
    if not isinstance(value, (list, tuple)):
        return rows
    for row in value:
        if isinstance(row, Mapping) and "agent" in row:
            rows.append(
                {
                    "agent": str(row["agent"]),
                    "median_seconds": row.get("median_seconds"),
                    "responses": _safe_int(row.get("responses")),
                }
            )
    return rows[:limit]


def _interaction_rankings(rankings: Any) -> dict[str, list[dict[str, Any]]]:
    default = {"top_responders": [], "top_targets": []}
    if not isinstance(rankings, Mapping):
        return default

    top_responders = []
    for row in rankings.get("top_responders") or []:
        if isinstance(row, Mapping) and "agent" in row:
            top_responders.append(
                {"agent": str(row["agent"]), "count": _safe_int(row.get("count"))}
            )

    top_targets = []
    for row in rankings.get("top_targets") or []:
        if isinstance(row, Mapping) and "agent" in row:
            top_targets.append(
                {"agent": str(row["agent"]), "count": _safe_int(row.get("count"))}
            )

    return {"top_responders": top_responders, "top_targets": top_targets}
