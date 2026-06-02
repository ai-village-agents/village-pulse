"""village_pulse.api_client — HTTP client for the AI Village public API.

This module talks to the read-only JSON endpoints under
``https://theaidigest.org/village/api/`` that power the village website.

It exposes a small surface that the rest of the Village Pulse pipeline relies
on:

* :class:`APIError` — single error type raised for HTTP / JSON failures.
* :class:`VillageAPIClient` — stateful client that resolves the village id by
  slug, caches the agent and chat-room directories, and paginates the events
  feed.
* :func:`fetch_events` — module-level convenience function with the exact
  signature ``village_pulse/__main__.py`` calls.

Each returned event is a flat ``dict`` with the keys
``analytics.normalize_event`` knows how to read:

    {
        "event_id":      str,    # api row id
        "event_index":   int,    # monotonic ordering key
        "agent_name":    str,    # resolved actor name ("" if unknown)
        "room":          str|None,   # human room name e.g. "best" / "rest"
        "room_id":       str|None,   # raw room uuid
        "created_at":    str,    # ISO-8601 UTC timestamp
        "action_type":   str,    # e.g. "AGENT_TALK", "USER_TALK", "PAUSE"
        "content":       str,    # message text (best effort)
        "cost":          int|None,
        "input_tokens":  int|None,
        "output_tokens": int|None,
        "raw":           dict,   # original ``event['data']`` payload
    }

The client is stdlib-friendly: it uses :mod:`requests` if available and falls
back to :mod:`urllib.request` otherwise, so unit tests can run in minimal
environments.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Iterable, Iterator, Mapping, Optional

try:  # optional dependency — declared in pyproject.toml
    import requests as _requests  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback exercised in tests
    _requests = None  # type: ignore[assignment]

__all__ = [
    "APIError",
    "DEFAULT_ENDPOINT",
    "DEFAULT_VILLAGE_SLUG",
    "VillageAPIClient",
    "fetch_events",
]

LOG = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://theaidigest.org/village/api/"
# The live AI Village is served under the slug "actual-launch-1"
# (village id 00ebc425-..., created 2025-04-02, ~245K events as of D427).
# Note: the public API also exposes a separate slug "village"
# (id c3b2ff3d-..., created 2025-05-15) which resolves but is empty
# (0 events). Don't accidentally swap to it.
DEFAULT_VILLAGE_SLUG = "actual-launch-1"
DEFAULT_USER_AGENT = (
    "village-pulse/0.1 (+https://github.com/ai-village-agents/village-pulse)"
)

# Action types that look like a chat-message (analytics.compute_all uses these
# too, but we don't import from analytics to avoid a cycle).
MESSAGE_ACTION_TYPES = frozenset({"AGENT_TALK", "USER_TALK"})


class APIError(RuntimeError):
    """Raised when the village API returns an HTTP error or unparseable body."""

    def __init__(
        self, message: str, *, status: Optional[int] = None, url: Optional[str] = None
    ):
        super().__init__(message)
        self.status = status
        self.url = url

    def __str__(self) -> str:  # pragma: no cover - trivial
        base = super().__str__()
        if self.status is not None:
            base = f"[HTTP {self.status}] {base}"
        if self.url:
            base = f"{base} ({self.url})"
        return base


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------


def _normalize_endpoint(endpoint: str) -> str:
    """Return ``endpoint`` with a trailing slash, raising on obvious garbage."""
    if not endpoint or not isinstance(endpoint, str):
        raise APIError(f"endpoint must be a non-empty string, got {endpoint!r}")
    endpoint = endpoint.strip()
    if not endpoint.startswith(("http://", "https://")):
        raise APIError(f"endpoint must be http(s)://..., got {endpoint!r}")
    if not endpoint.endswith("/"):
        endpoint += "/"
    return endpoint


def _http_get_json(
    url: str,
    *,
    timeout: float = 15.0,
    max_retries: int = 3,
    backoff: float = 1.0,
    session: Any = None,
) -> Any:
    """GET ``url`` and decode JSON, retrying transient errors with backoff.

    Uses :mod:`requests` if installed, otherwise stdlib ``urllib``.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, max_retries + 1):
        try:
            if _requests is not None:
                sess = session or _requests
                resp = sess.get(
                    url, timeout=timeout, headers={"User-Agent": DEFAULT_USER_AGENT}
                )
                status = resp.status_code
                if status >= 400:
                    body = (resp.text or "")[:200]
                    raise APIError(f"GET failed: {body}", status=status, url=url)
                try:
                    return resp.json()
                except ValueError as exc:
                    raise APIError(
                        f"invalid JSON: {exc}", status=status, url=url
                    ) from exc
            else:  # urllib fallback
                req = urllib.request.Request(
                    url, headers={"User-Agent": DEFAULT_USER_AGENT}
                )
                with urllib.request.urlopen(req, timeout=timeout) as fh:  # noqa: S310 - trusted host
                    raw = fh.read()
                try:
                    return json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise APIError(f"invalid JSON: {exc}", url=url) from exc
        except APIError as exc:
            # Only retry server / transient errors; bail immediately on 4xx.
            if exc.status is not None and 400 <= exc.status < 500:
                raise
            last_exc = exc
        except Exception as exc:  # network errors, timeouts, etc.
            last_exc = exc
        if attempt < max_retries:
            sleep_s = backoff * (2 ** (attempt - 1))
            LOG.warning(
                "GET %s attempt %d/%d failed: %s — retrying in %.1fs",
                url,
                attempt,
                max_retries,
                last_exc,
                sleep_s,
            )
            time.sleep(sleep_s)
    # exhausted
    if isinstance(last_exc, APIError):
        raise last_exc
    raise APIError(f"GET failed after {max_retries} attempts: {last_exc}", url=url)


def _qs(params: Mapping[str, Any]) -> str:
    """URL-encode a query-string, dropping ``None`` values."""
    pairs = [(k, v) for k, v in params.items() if v is not None]
    return urllib.parse.urlencode(pairs)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class VillageAPIClient:
    """Thin, cached client for the village JSON API.

    Parameters
    ----------
    endpoint:
        Base URL of the village API. Trailing slash is added if missing.
    village_slug:
        Slug of the village (default ``"actual-launch-1"``).
    village_id:
        If you already know the village UUID, pass it to skip the slug lookup.
    session:
        Optional :class:`requests.Session` (or compatible) for connection reuse.
    timeout:
        Per-request timeout in seconds.
    max_retries:
        Maximum number of attempts for each GET. Transient errors back off
        exponentially; 4xx responses are raised immediately.
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        village_slug: str = DEFAULT_VILLAGE_SLUG,
        village_id: Optional[str] = None,
        session: Any = None,
        timeout: float = 15.0,
        max_retries: int = 3,
    ) -> None:
        self.endpoint = _normalize_endpoint(endpoint)
        self.village_slug = village_slug
        self._village_id = village_id
        self._village_detail: Optional[dict] = None
        self._agents_by_id: Optional[dict[str, str]] = None
        self._rooms_by_id: Optional[dict[str, str]] = None
        self._session = session
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)

    # ------------------------------------------------------------------ basics

    def _get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        url = urllib.parse.urljoin(self.endpoint, path.lstrip("/"))
        if params:
            url = f"{url}?{_qs(params)}"
        return _http_get_json(
            url,
            timeout=self.timeout,
            max_retries=self.max_retries,
            session=self._session,
        )

    # --------------------------------------------------------------- metadata

    @property
    def village_id(self) -> str:
        """Resolve and cache the village UUID for ``self.village_slug``."""
        if self._village_id:
            return self._village_id
        data = self._get("villages", {"slug": self.village_slug})
        if isinstance(data, dict) and data.get("id"):
            self._village_id = str(data["id"])
            return self._village_id
        raise APIError(
            f"could not resolve village slug {self.village_slug!r}: {data!r}"
        )

    def get_village(self, *, refresh: bool = False) -> dict:
        """Return the full village detail blob (cached)."""
        if self._village_detail is None or refresh:
            self._village_detail = self._get(f"villages/{self.village_id}")
        return dict(self._village_detail or {})

    def get_agents(self, *, refresh: bool = False) -> dict[str, str]:
        """Return ``{agent_uuid: agent_name}`` for every agent in the village."""
        if self._agents_by_id is None or refresh:
            v = self.get_village(refresh=refresh)
            mapping: dict[str, str] = {}
            for a in v.get("agents", []) or []:
                if isinstance(a, Mapping) and a.get("id"):
                    mapping[str(a["id"])] = str(a.get("name") or "")
            # active agent is sometimes in its own field
            active = v.get("activeAgent")
            if isinstance(active, Mapping) and active.get("id"):
                mapping.setdefault(str(active["id"]), str(active.get("name") or ""))
            self._agents_by_id = mapping
        return dict(self._agents_by_id)

    def get_rooms(self, *, refresh: bool = False) -> dict[str, str]:
        """Return ``{room_uuid: room_name}`` for every chat room."""
        if self._rooms_by_id is None or refresh:
            v = self.get_village(refresh=refresh)
            mapping: dict[str, str] = {}
            for r in v.get("chatRooms", []) or []:
                if isinstance(r, Mapping) and r.get("id"):
                    mapping[str(r["id"])] = str(r.get("name") or "")
            self._rooms_by_id = mapping
        return dict(self._rooms_by_id)

    # ----------------------------------------------------------------- events

    def iter_raw_events_for_day(
        self,
        day: Optional[int] = None,
        *,
        max_pages: int = 200,
    ) -> Iterator[dict]:
        """Yield raw event rows (verbatim from the API) for one ``day``.

        ``day`` is the village day-number (1-indexed). ``None`` returns the
        most-recent feed (whatever the API serves with no ``day`` filter).
        """
        page = 1
        while page <= max_pages:
            params: dict[str, Any] = {"villageId": self.village_id, "page": page}
            if day is not None:
                params["day"] = int(day)
            data = self._get("events", params)
            events = data.get("events") if isinstance(data, Mapping) else None
            if not events:
                return
            for ev in events:
                if isinstance(ev, Mapping):
                    yield dict(ev)
            if not data.get("hasMore"):
                return
            page += 1

    def fetch_events(
        self,
        *,
        days: int = 7,
        current_day: Optional[int] = None,
        room: Optional[str] = None,
        agent: Optional[str] = None,
        action_types: Optional[Iterable[str]] = None,
    ) -> list[dict]:
        """Fetch and flatten events for the trailing ``days`` village days.

        Parameters
        ----------
        days:
            Number of past village-days to include. ``1`` means *today only*.
        current_day:
            Override the current village day (mainly for tests). If ``None``,
            the latest day is discovered from the most-recent events feed.
        room:
            Optional room-name filter (matches ``room`` after resolution,
            case-insensitive; ``"#best"`` and ``"best"`` both work).
        agent:
            Optional agent-name filter (case-insensitive substring match).
        action_types:
            Optional iterable of action types to keep
            (case-insensitive). ``None`` keeps everything.

        Returns
        -------
        list[dict]
            Flat events with the schema documented in the module docstring,
            ordered oldest-first (so analytics' day-bucketing is natural).
        """
        if days < 1:
            raise ValueError("days must be >= 1")

        agents = self.get_agents()
        rooms = self.get_rooms()

        latest = current_day if current_day is not None else self._discover_latest_day()
        if latest is None:
            # fall back to "no day filter" — pull the top-of-feed only
            day_range: list[Optional[int]] = [None]
        else:
            day_range = [latest - i for i in range(days) if latest - i >= 1]

        keep_types: Optional[set[str]] = None
        if action_types is not None:
            keep_types = {str(t).upper() for t in action_types}

        room_norm = _normalize_room_filter(room)
        agent_norm = (agent or "").strip().lower() or None

        out: list[dict] = []
        for d in day_range:
            for raw in self.iter_raw_events_for_day(d):
                flat = _flatten_event(raw, agents=agents, rooms=rooms)
                if keep_types is not None and flat["action_type"] not in keep_types:
                    continue
                if room_norm is not None and _norm(flat.get("room")) != room_norm:
                    continue
                if (
                    agent_norm is not None
                    and agent_norm not in flat["agent_name"].lower()
                ):
                    continue
                out.append(flat)
        # API returns newest-first within a page; we want oldest-first across
        # the whole window so daily buckets line up.
        out.sort(key=lambda e: e.get("event_index") or 0)
        return out

    # ----------------------------------------------------------- internal

    def _discover_latest_day(self) -> Optional[int]:
        """Best-effort discovery of the current village day-number.

        The events feed does not include a day-number in each row, but the
        front-end uses sequential integers starting at 1 the day the village
        launched (2025-04-02). We compute it from the village's
        ``createdAt`` timestamp.
        """
        v = self.get_village()
        created = v.get("createdAt")
        if not created:
            return None
        try:
            from datetime import datetime, timezone

            t = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            now = datetime.now(tz=timezone.utc)
            delta_days = (now.date() - t.date()).days
            return max(1, delta_days + 1)
        except Exception:  # pragma: no cover - paranoid fallback
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip().lstrip("#").lower()


def _normalize_room_filter(room: Optional[str]) -> Optional[str]:
    if not room:
        return None
    return _norm(room) or None


def _flatten_event(
    raw: Mapping[str, Any],
    *,
    agents: Mapping[str, str],
    rooms: Mapping[str, str],
) -> dict:
    """Flatten a raw API event row into the schema analytics expects."""
    data = raw.get("data") if isinstance(raw.get("data"), Mapping) else {}
    data = data or {}
    action_type = str(data.get("actionType") or "").upper()

    speaker_id = data.get("speakerId") or data.get("agentId") or data.get("userId")
    speaker_type = data.get("speakerType")
    # Prefer the resolved name; fall back to fields the API may already set.
    agent_name = ""
    if speaker_id and str(speaker_id) in agents:
        agent_name = agents[str(speaker_id)]
    if not agent_name:
        agent_name = str(
            data.get("agentName")
            or data.get("userName")
            or data.get("speakerName")
            or ""
        )

    room_uuid = data.get("roomId")
    room_name = rooms.get(str(room_uuid)) if room_uuid else None

    content = data.get("content")
    if not isinstance(content, str):
        # Some action types (CONSOLIDATE, SEARCH_HISTORY) have content elsewhere.
        content = (
            data.get("nextSessionGoal") or data.get("query") or data.get("text") or ""
        )
    if not isinstance(content, str):
        content = str(content)

    flat: dict[str, Any] = {
        "event_id": raw.get("id"),
        "event_index": raw.get("eventIndex"),
        "agent_name": agent_name,
        "room": room_name,
        "room_id": str(room_uuid) if room_uuid else None,
        "created_at": raw.get("createdAt"),
        "action_type": action_type,
        "content": content,
        "speaker_type": speaker_type,
        "cost": data.get("cost"),
        "input_tokens": data.get("inputTokens"),
        "output_tokens": data.get("outputTokens"),
        "raw": dict(data),
    }
    return flat


# ---------------------------------------------------------------------------
# Module-level convenience entry point (__main__ wires here)
# ---------------------------------------------------------------------------


def fetch_events(
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    days: int = 7,
    room: Optional[str] = None,
    agent: Optional[str] = None,
    village_slug: str = DEFAULT_VILLAGE_SLUG,
    village_id: Optional[str] = None,
    action_types: Optional[Iterable[str]] = None,
    current_day: Optional[int] = None,
) -> list[dict]:
    """Convenience wrapper: build a :class:`VillageAPIClient` and fetch events.

    The signature matches what ``village_pulse/__main__.py`` passes.
    """
    client = VillageAPIClient(
        endpoint=endpoint,
        village_slug=village_slug,
        village_id=village_id,
    )
    return client.fetch_events(
        days=days,
        room=room,
        agent=agent,
        action_types=action_types,
        current_day=current_day,
    )
