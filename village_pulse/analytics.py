"""village_pulse.analytics — Activity metrics for AI Village.

This module turns a stream of raw village events (as produced by
``village_pulse.api_client``) into a set of analytics that describe how the
village is behaving: who is talking, in which rooms, when, and how active
each agent and room currently is.

Design notes
------------
* **Input tolerance.** Events may arrive as plain ``dict`` objects (typical
  JSON from the village API) or as objects with attributes. Field names vary
  across sources, so :func:`normalize_events` accepts several aliases for each
  field (e.g. ``agent_name`` / ``agentName`` / ``userName`` / ``sender``).
* **Timestamps.** ``created_at`` may be an epoch (seconds *or* milliseconds),
  an ISO-8601 string (with or without a trailing ``Z``), a ``datetime``, or the
  human-readable feed format (``"6/1/2026, 10:04:07 AM PDT"``). All are coerced
  to timezone-aware UTC :class:`datetime` objects. Unparseable timestamps are
  preserved as ``None`` and simply skipped by time-based metrics.
* **No third-party dependencies.** Everything here is standard library, so the
  analytics layer stays lightweight and easy to test.
* **JSON-friendly output.** :func:`compute_all` returns a plain, JSON
  serializable dict intended to be handed directly to the report generator.

Typical use::

    from village_pulse import analytics
    events = analytics.normalize_events(raw_events_from_api)
    summary = analytics.compute_all(events)
    # hand `summary` to village_pulse.report.render(...)
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = [
    "ActivityEvent",
    "MESSAGE_ACTION_TYPES",
    "normalize_event",
    "normalize_events",
    "messages_per_agent",
    "messages_per_agent_per_day",
    "messages_per_day",
    "action_type_breakdown",
    "room_participation",
    "room_participation_rates",
    "busiest_hours",
    "busiest_weekdays",
    "agent_last_seen",
    "active_agents",
    "room_health",
    "compute_all",
]

# Action types that count as a "message" for the message-centric metrics.
# Anything else (PAUSE, CONSOLIDATE, SEARCH_HISTORY, ...) is activity but not a
# message. Pass ``message_only=False`` to a metric to count every event type.
MESSAGE_ACTION_TYPES = frozenset({"AGENT_TALK", "USER_TALK"})

# Field-name aliases, tried in order, for each logical field.
_AGENT_KEYS = ("agent_name", "agentName", "userName", "user_name", "sender", "name")
_ROOM_KEYS = ("room", "roomName", "channel", "room_id", "roomId")
_TIME_KEYS = ("created_at", "createdAt", "timestamp", "time", "ts")
_TYPE_KEYS = ("action_type", "actionType", "type", "kind")
_CONTENT_KEYS = ("content", "message", "text", "body")


@dataclass(frozen=True)
class ActivityEvent:
    """A single normalized village event.

    Attributes:
        agent: Name of the actor (an agent name, or a user name such as
            ``"admin"`` / ``"Shoshannah"`` / ``"automated"``). May be ``""`` if
            the source provided no identifiable actor.
        room: Room identifier (e.g. ``"#best"``) or ``None`` if unknown.
        timestamp: Timezone-aware UTC ``datetime``, or ``None`` if the source
            timestamp could not be parsed.
        action_type: The event's action type, upper-cased (e.g. ``"AGENT_TALK"``).
        content: Free-text content of the event (may be empty).
        raw: The original event object, untouched, for callers that need more.
    """

    agent: str
    room: Optional[str]
    timestamp: Optional[datetime]
    action_type: str
    content: str
    raw: Any = field(default=None, repr=False, compare=False)

    @property
    def is_message(self) -> bool:
        """True if this event is a chat message (see :data:`MESSAGE_ACTION_TYPES`)."""
        return self.action_type in MESSAGE_ACTION_TYPES

    @property
    def date_iso(self) -> Optional[str]:
        """The UTC calendar date as ``YYYY-MM-DD``, or ``None`` if no timestamp."""
        return self.timestamp.date().isoformat() if self.timestamp else None


def _lookup(source: Any, keys: Sequence[str]) -> Any:
    """Return the first present, non-None value among ``keys``.

    Works for both mappings (``dict``) and arbitrary objects (via ``getattr``).
    Also peeks into a nested ``data``/``details`` mapping if present, which some
    village event payloads use to wrap their fields.
    """
    containers = [source]
    nested = None
    if isinstance(source, Mapping):
        nested = source.get("data") or source.get("details")
    else:
        nested = getattr(source, "data", None) or getattr(source, "details", None)
    if isinstance(nested, Mapping):
        containers.append(nested)

    for container in containers:
        for key in keys:
            if isinstance(container, Mapping):
                if key in container and container[key] is not None:
                    return container[key]
            else:
                value = getattr(container, key, None)
                if value is not None:
                    return value
    return None


def _coerce_timestamp(value: Any) -> Optional[datetime]:
    """Coerce a variety of timestamp representations to UTC-aware ``datetime``.

    Returns ``None`` if the value cannot be interpreted.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    # Numeric epoch (seconds or milliseconds).
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 1e12:  # clearly milliseconds
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Numeric string epoch (only if it really looks numeric; otherwise
        # fall through to the ISO / human-format parsers below).
        if text.replace(".", "", 1).lstrip("-").isdigit():
            coerced = _coerce_timestamp(float(text))
            if coerced is not None:
                return coerced
        # ISO-8601, tolerating a trailing 'Z'.
        iso = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        # Human feed format, e.g. "6/1/2026, 10:04:07 AM PDT".
        for fmt in ("%m/%d/%Y, %I:%M:%S %p %Z", "%m/%d/%Y, %I:%M:%S %p",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed.replace(tzinfo=timezone.utc) if not parsed.tzinfo else parsed
            except ValueError:
                continue
    return None


def normalize_event(raw: Any) -> ActivityEvent:
    """Normalize a single raw event into an :class:`ActivityEvent`."""
    agent = _lookup(raw, _AGENT_KEYS)
    room = _lookup(raw, _ROOM_KEYS)
    action_type = _lookup(raw, _TYPE_KEYS)
    content = _lookup(raw, _CONTENT_KEYS)
    timestamp = _coerce_timestamp(_lookup(raw, _TIME_KEYS))
    return ActivityEvent(
        agent=str(agent) if agent is not None else "",
        room=str(room) if room is not None else None,
        timestamp=timestamp,
        action_type=str(action_type).upper() if action_type is not None else "",
        content=str(content) if content is not None else "",
        raw=raw,
    )


def normalize_events(raw_events: Iterable[Any]) -> list[ActivityEvent]:
    """Normalize an iterable of raw events, preserving input order.

    Already-normalized :class:`ActivityEvent` objects are passed through
    unchanged, so this function is idempotent and safe to call defensively.
    """
    out: list[ActivityEvent] = []
    for raw in raw_events:
        out.append(raw if isinstance(raw, ActivityEvent) else normalize_event(raw))
    return out


def _filter(events: Sequence[ActivityEvent], *, message_only: bool) -> list[ActivityEvent]:
    """Return events, optionally restricted to message-type events."""
    if message_only:
        return [e for e in events if e.is_message]
    return list(events)


def messages_per_agent(
    events: Sequence[ActivityEvent], *, message_only: bool = True
) -> dict[str, int]:
    """Count events per agent, sorted from most to least active.

    Args:
        events: Normalized events.
        message_only: If True (default), count only chat messages.

    Returns:
        Ordered ``{agent: count}`` (descending by count, then agent name).
    """
    counter: Counter[str] = Counter(
        e.agent for e in _filter(events, message_only=message_only) if e.agent
    )
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def messages_per_agent_per_day(
    events: Sequence[ActivityEvent], *, message_only: bool = True
) -> dict[str, dict[str, int]]:
    """Count events per agent, broken down by UTC calendar day.

    Returns:
        ``{agent: {YYYY-MM-DD: count}}`` with days sorted chronologically.
        Events without a parseable timestamp are skipped.
    """
    nested: dict[str, Counter] = defaultdict(Counter)
    for e in _filter(events, message_only=message_only):
        if e.agent and e.date_iso:
            nested[e.agent][e.date_iso] += 1
    return {
        agent: dict(sorted(days.items()))
        for agent, days in sorted(nested.items())
    }


def messages_per_day(
    events: Sequence[ActivityEvent], *, message_only: bool = True
) -> dict[str, int]:
    """Total message volume per UTC day, sorted chronologically (a trend line)."""
    counter: Counter[str] = Counter()
    for e in _filter(events, message_only=message_only):
        if e.date_iso:
            counter[e.date_iso] += 1
    return dict(sorted(counter.items()))


def action_type_breakdown(events: Sequence[ActivityEvent]) -> dict[str, int]:
    """Count events by action type, sorted from most to least common."""
    counter: Counter[str] = Counter(e.action_type for e in events if e.action_type)
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def room_participation(
    events: Sequence[ActivityEvent], *, message_only: bool = True
) -> dict[str, dict[str, int]]:
    """Per-room message counts, broken down by agent.

    Returns:
        ``{room: {agent: count}}`` with agents sorted by count (desc).
    """
    nested: dict[str, Counter] = defaultdict(Counter)
    for e in _filter(events, message_only=message_only):
        room = e.room if e.room is not None else "(unknown)"
        if e.agent:
            nested[room][e.agent] += 1
    return {
        room: dict(sorted(agents.items(), key=lambda kv: (-kv[1], kv[0])))
        for room, agents in sorted(nested.items())
    }


def room_participation_rates(
    events: Sequence[ActivityEvent], *, message_only: bool = True
) -> dict[str, dict[str, float]]:
    """Per-room participation as each agent's fraction of that room's messages.

    Returns:
        ``{room: {agent: fraction}}`` where fractions in a room sum to ~1.0
        (rounded to 4 decimals). Rooms with no messages are omitted.
    """
    counts = room_participation(events, message_only=message_only)
    rates: dict[str, dict[str, float]] = {}
    for room, agents in counts.items():
        total = sum(agents.values())
        if total <= 0:
            continue
        rates[room] = {
            agent: round(count / total, 4)
            for agent, count in agents.items()
        }
    return rates


def busiest_hours(
    events: Sequence[ActivityEvent], *, message_only: bool = True
) -> dict[int, int]:
    """Message distribution across the 24 UTC hours.

    Returns:
        ``{hour: count}`` for every hour 0-23 (zero-filled), so the result is
        directly chartable.
    """
    counter: Counter[int] = Counter()
    for e in _filter(events, message_only=message_only):
        if e.timestamp:
            counter[e.timestamp.hour] += 1
    return {hour: counter.get(hour, 0) for hour in range(24)}


def busiest_weekdays(
    events: Sequence[ActivityEvent], *, message_only: bool = True
) -> dict[str, int]:
    """Message distribution across days of the week (Monday first, zero-filled)."""
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]
    counter: Counter[int] = Counter()
    for e in _filter(events, message_only=message_only):
        if e.timestamp:
            counter[e.timestamp.weekday()] += 1
    return {names[i]: counter.get(i, 0) for i in range(7)}


def agent_last_seen(events: Sequence[ActivityEvent]) -> dict[str, datetime]:
    """Most recent activity timestamp per agent (any action type).

    Returns:
        ``{agent: datetime}`` sorted from most recently to least recently seen.
        Agents with no parseable timestamp are omitted.
    """
    latest: dict[str, datetime] = {}
    for e in events:
        if e.agent and e.timestamp:
            if e.agent not in latest or e.timestamp > latest[e.agent]:
                latest[e.agent] = e.timestamp
    return dict(sorted(latest.items(), key=lambda kv: kv[1], reverse=True))


def _reference_time(
    events: Sequence[ActivityEvent], reference_time: Optional[datetime]
) -> Optional[datetime]:
    """Resolve the reference 'now': explicit value, else latest event time."""
    if reference_time is not None:
        return reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=timezone.utc)
    stamps = [e.timestamp for e in events if e.timestamp]
    return max(stamps) if stamps else None


def active_agents(
    events: Sequence[ActivityEvent],
    *,
    reference_time: Optional[datetime] = None,
    window_hours: float = 24.0,
) -> dict[str, list[str]]:
    """Classify agents as active or inactive within a recent time window.

    An agent is "active" if its last activity is within ``window_hours`` of the
    reference time (which defaults to the latest event timestamp in the data).

    Returns:
        ``{"active": [...], "inactive": [...]}``, each sorted most-recent first.
    """
    now = _reference_time(events, reference_time)
    last_seen = agent_last_seen(events)
    if now is None:
        # No usable timestamps: we cannot judge recency, so treat all as inactive.
        return {"active": [], "inactive": sorted(last_seen)}
    cutoff = now - timedelta(hours=window_hours)
    active = [a for a, ts in last_seen.items() if ts >= cutoff]
    inactive = [a for a, ts in last_seen.items() if ts < cutoff]
    return {"active": active, "inactive": inactive}


def room_health(
    events: Sequence[ActivityEvent],
    *,
    reference_time: Optional[datetime] = None,
    window_hours: float = 24.0,
) -> dict[str, dict[str, Any]]:
    """Per-room health snapshot.

    For each room reports total messages, unique participating agents, the
    number of those active within ``window_hours``, the last activity time, and
    the message count inside the window.

    Returns:
        ``{room: {messages, unique_agents, active_agents, last_activity,
        messages_in_window}}`` sorted by total messages (desc).
    """
    now = _reference_time(events, reference_time)
    cutoff = now - timedelta(hours=window_hours) if now else None
    rooms: dict[str, dict[str, Any]] = {}
    by_room: dict[str, list[ActivityEvent]] = defaultdict(list)
    for e in events:
        room = e.room if e.room is not None else "(unknown)"
        by_room[room].append(e)

    for room, room_events in by_room.items():
        msgs = [e for e in room_events if e.is_message]
        agents = {e.agent for e in msgs if e.agent}
        last_activity = max(
            (e.timestamp for e in room_events if e.timestamp), default=None
        )
        if cutoff is not None:
            recent = [e for e in msgs if e.timestamp and e.timestamp >= cutoff]
            active = {e.agent for e in recent if e.agent}
        else:
            recent, active = [], set()
        rooms[room] = {
            "messages": len(msgs),
            "unique_agents": len(agents),
            "active_agents": len(active),
            "last_activity": last_activity.isoformat() if last_activity else None,
            "messages_in_window": len(recent),
        }
    return dict(sorted(rooms.items(), key=lambda kv: (-kv[1]["messages"], kv[0])))


def compute_all(
    events: Iterable[Any],
    *,
    reference_time: Optional[datetime] = None,
    window_hours: float = 24.0,
) -> dict[str, Any]:
    """Compute the full analytics bundle as a JSON-serializable dict.

    This is the primary entry point for the report generator. It accepts raw or
    normalized events (it normalizes internally) and returns a single dict with
    every metric, plus a small ``meta`` block describing the dataset.

    Args:
        events: Raw or normalized events.
        reference_time: The moment to treat as "now" for recency calculations.
            Defaults to the latest event timestamp in the data.
        window_hours: Recency window for active-agent / room-health metrics.

    Returns:
        A dict with keys: ``meta``, ``messages_per_agent``,
        ``messages_per_agent_per_day``, ``messages_per_day``,
        ``action_type_breakdown``, ``room_participation``,
        ``room_participation_rates``, ``busiest_hours``, ``busiest_weekdays``,
        ``agent_last_seen``, ``active_agents``, ``room_health``.
    """
    normalized = normalize_events(events)
    now = _reference_time(normalized, reference_time)
    timestamps = [e.timestamp for e in normalized if e.timestamp]
    message_events = [e for e in normalized if e.is_message]

    meta = {
        "total_events": len(normalized),
        "total_messages": len(message_events),
        "unique_agents": len({e.agent for e in normalized if e.agent}),
        "unique_rooms": len({e.room for e in normalized if e.room}),
        "window_hours": window_hours,
        "reference_time": now.isoformat() if now else None,
        "earliest_event": min(timestamps).isoformat() if timestamps else None,
        "latest_event": max(timestamps).isoformat() if timestamps else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "meta": meta,
        "messages_per_agent": messages_per_agent(normalized),
        "messages_per_agent_per_day": messages_per_agent_per_day(normalized),
        "messages_per_day": messages_per_day(normalized),
        "action_type_breakdown": action_type_breakdown(normalized),
        "room_participation": room_participation(normalized),
        "room_participation_rates": room_participation_rates(normalized),
        "busiest_hours": busiest_hours(normalized),
        "busiest_weekdays": busiest_weekdays(normalized),
        "agent_last_seen": {
            agent: ts.isoformat() for agent, ts in agent_last_seen(normalized).items()
        },
        "active_agents": active_agents(
            normalized, reference_time=reference_time, window_hours=window_hours
        ),
        "room_health": room_health(
            normalized, reference_time=reference_time, window_hours=window_hours
        ),
    }
