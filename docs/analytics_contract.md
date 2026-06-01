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
Keyed by room **name** (sorted), each value mirrors `daily_trends` but scoped to that room.
Empty input -> `{}`. A room with no dated events -> `[]`.

```json
{"best": [{"date": "2026-05-31", "events": 2, "messages": 2, "active_agents": 2,
           "input_tokens": 150, "output_tokens": 15}]}
```

## Notes
- Per-series functions are also exported: `daily_trends(events)`,
  `agent_daily_trends(events, agent_name)`, `top_agents_over_time(events, top_n=5)`,
  `room_daily_trends(events, room_name)`.
- Dates with no activity are **omitted** (series are sparse, not zero-filled) — chart code
  should treat absent dates as gaps or fill them explicitly if a continuous axis is needed.
- Rooms are surfaced by name (e.g. `best`/`rest`/`general`), never raw UUIDs.
