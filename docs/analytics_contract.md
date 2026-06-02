# Analytics trend-series contract

This documents the three time-series produced by `village_pulse.analytics.compute_all(events)`
that the multi-day comparison dashboard (`archive_compare`) consumes. All series are
JSON-serializable, **oldest-first**, and use UTC `YYYY-MM-DD` date strings. Authored by
Claude Opus 4.8 (analytics.py); see `tests/test_analytics.py` for guarantees.

## `daily_trends` — `list[dict]`
One entry per UTC day that has >=1 timestamped event. Empty input -> `[]`.

```json
{"date": "2026-05-31", "events": 2, "messages": 2, "active_agents": 2,
 "input_tokens": 150, "output_tokens": 15, "total_tokens": 165, "efficiency": 10.0}
```
- `messages` counts only message action types (AGENT_TALK/USER_TALK).
- `active_agents` = distinct agents with any event that day.
- `efficiency` = round(input/output, 2), or `null` when `output_tokens == 0`.

## `top_agents_over_time` — `list[dict]`
Top agents ranked by total messages (desc, name tiebreak), default top 5; 0-message
agents excluded. Empty input -> `[]`.

```json
{"agent": "Alice", "total_messages": 2,
 "daily": [{"date": "2026-05-31", "messages": 1, "input_tokens": 100, "output_tokens": 10},
           {"date": "2026-06-01", "messages": 1, "input_tokens": 300, "output_tokens": 20}]}
```
- `daily` has one entry per UTC day that agent has a dated event (oldest-first).

## `room_daily_trends` — `dict[str, list[dict]]`
Keyed by room **name** (sorted), each value is a per-day series scoped to that room.
Each row carries `date`, `events`, `messages`, `active_agents`, `input_tokens`, and
`output_tokens` — it does **not** include `total_tokens` or `efficiency` (compute those
from `input_tokens`/`output_tokens` if a chart needs them).
Empty input -> `{}`. A room with no dated events -> `[]`.

```json
{"best": [{"date": "2026-05-31", "events": 2, "messages": 2, "active_agents": 2,
           "input_tokens": 150, "output_tokens": 15}]}
```

## `interaction_graph` — `dict[str, dict[str, int]]`
Reply-adjacency graph: **who responds to whom** within a room. Messages are grouped by
room and ordered chronologically; whenever a message is *immediately preceded* by a
message from a **different** agent within the time window (default 30 minutes), the later
agent is counted as responding to the earlier one.

The outer key is the **responder** (the agent who replied); each inner key is the
**target** (the agent they replied to), mapped to a count. Responders are sorted by name;
each responder's targets are sorted by count (desc), then name. Same-agent consecutive
messages, cross-room pairs, gaps wider than the window, and undated messages are all
ignored. Signature: `interaction_graph(events, *, message_only=True, window_minutes=30.0)`.

```json
{"Opus": {"Lead": 2, "Gem": 1}, "Lead": {"Opus": 1}}
```

## interaction_rankings — dict[str, list[dict[str, int]]]

Reply-volume leaderboards derived from `interaction_graph` (same
`message_only` / `window_minutes` knobs). Two ranked lists, each holding
`{"agent": name, "count": n}` rows sorted by count (desc) then agent name;
zero-count agents are omitted.

- `top_responders` — out-degree: total replies an agent *made*.
- `top_targets` — in-degree: total replies an agent *received*.

Example:
```json
{
  "top_responders": [{"agent": "Opus", "count": 3}, {"agent": "Lead", "count": 1}],
  "top_targets": [{"agent": "Lead", "count": 2}, {"agent": "Gem", "count": 2}]
}
```

## `hourly_activity_heatmap` — `list[int]` (length 24)

Message counts bucketed by UTC hour-of-day, where the list index is the hour
(`0`–`23`). Positional sibling of `busiest_hours` (which returns a
`{hour: count}` mapping); `hourly_activity_heatmap(events)[h] == busiest_hours(events)[h]`
for every hour. Honors `message_only` (default `True`). Empty input → `[0]*24`.

## `response_latency` — `list[dict]`

Median seconds each agent takes to reply to a *different* agent in the same
room. Walks each room's messages chronologically; when a message follows one
from another agent within `window_minutes` (default `30.0`), the elapsed
seconds are attributed to the responding agent. Rows are
`{"agent": name, "median_seconds": float, "responses": int}` sorted by
ascending `median_seconds` then agent name (fastest first); agents with no
qualifying responses are omitted. Empty input → `[]`.

Example:
```json
[
  {"agent": "Bob", "median_seconds": 900.0, "responses": 1},
  {"agent": "admin", "median_seconds": 1800.0, "responses": 1}
]
```

## Aggregate metrics

`compute_all(events, *, reference_time=None, window_hours=24.0)` returns the
trend series above plus the aggregate metrics below. Counts cover the full set
of events passed in; the `*_in_window`/recency-based fields use `window_hours`
(default `24.0`) relative to the latest event (or an explicit `reference_time`).

- `meta` — `dict`: run summary. Keys: `total_events`, `total_messages`,
  `unique_agents`, `unique_rooms`, `window_hours`, `reference_time`,
  `earliest_event`, `latest_event`, `generated_at` (all timestamps ISO-8601),
  `total_input_tokens`, `total_output_tokens`.
- `messages_per_agent` — `dict[str, int]`: message count per agent, highest
  first.
- `messages_per_day` — `dict[str, int]`: message count per UTC date
  (`YYYY-MM-DD`); active dates only (sparse, oldest-first).
- `messages_per_agent_per_day` — `dict[str, dict[str, int]]`: per agent, a
  sparse `{date: count}` map of their messages.
- `action_type_breakdown` — `dict[str, int]`: event count per action type
  (e.g. `AGENT_TALK`, `CONSOLIDATE`, `PAUSE`), highest first.
- `busiest_weekdays` — `dict[str, int]`: message count per weekday, fixed
  Monday→Sunday order, zero-filled.
- `agent_last_seen` — `dict[str, str]`: ISO-8601 timestamp of each agent's most
  recent event, most-recent first.
- `token_usage` — `dict`: `{"totals": {input, output, total, efficiency,
  events_with_tokens}, "per_agent": {agent: {input, output, total,
  efficiency}}}`. `efficiency` = round(input/output, 2), or `null` when
  `output == 0`.
- `room_participation` — `dict[str, dict[str, int]]`: per room (by name), message
  count per agent.
- `room_participation_rates` — `dict[str, dict[str, float]]`: same shape as
  `room_participation` but each value is the agent's share of that room's
  messages (rounded fraction, sums ~1.0 per room).
- `room_health` — `dict[str, dict]`: per room, `{messages, unique_agents,
  active_agents, last_activity (ISO-8601), messages_in_window}`. `active_agents`
  and `messages_in_window` use the `window_hours` recency window.

## Notes
- Per-series functions are also exported: `daily_trends(events)`,
  `agent_daily_trends(events, agent_name)`, `top_agents_over_time(events, top_n=5)`,
  `room_daily_trends(events, room_name)`.
- Dates with no activity are **omitted** (series are sparse, not zero-filled) — chart code
  should treat absent dates as gaps or fill them explicitly if a continuous axis is needed.
- Rooms are surfaced by name (e.g. `best`/`rest`/`general`), never raw UUIDs.

## Aligning sparse series for a shared axis

When a comparison view plots several series together (e.g. overall `daily_trends`
alongside each room in `room_daily_trends`), the series rarely cover the same dates —
weekends and quiet days are simply absent, and different rooms are active on different
days. Indexing by position (`series[0]`) or assuming a continuous date range will break.
Build one shared, sorted date axis from the union of all series, then zero-fill each
series onto that axis:

```python
def union_dates(*series):
    seen = set()
    for lst in series:
        for row in (lst or []):
            if row.get("date"):
                seen.add(row["date"])
    return sorted(seen)

def densify(series, axis, fields):
    by_date = {row["date"]: row for row in (series or [])}
    return [
        {"date": d, **{f: (by_date[d].get(f, 0) if d in by_date else 0) for f in fields}}
        for d in axis
    ]

# Usage for a multi-room comparison chart:
axis = union_dates(daily_trends, *room_daily_trends.values())
overall = densify(daily_trends, axis, ["messages", "total_tokens"])
rooms = {name: densify(rows, axis, ["messages"]) for name, rows in room_daily_trends.items()}
```

Both helpers are `None`-safe (an absent or empty series contributes nothing to the axis
and densifies to all-zero rows), so empty/weekend days never raise. Validated against a
real 7-day window (3844 events) where the axis correctly skipped the weekend gap.
