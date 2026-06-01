"""Unit tests for village_pulse.api_client.

The tests stub out HTTP via a tiny fake transport so the suite remains hermetic
(no live network calls).  A separate ``test_live_smoke`` is skipped by default
and only runs when ``VILLAGE_PULSE_LIVE=1`` is set in the environment.
"""

from __future__ import annotations

import os
from typing import Any
from unittest import mock

import pytest

from village_pulse import api_client as ac


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, payload: Any, status: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status
        self.text = text or ""

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


def _fake_get_factory(responses):
    """Build a fake ``requests.get`` whose return value walks ``responses``."""
    iterator = iter(responses)

    def fake_get(url, *, timeout=None, headers=None):  # noqa: ARG001
        try:
            r = next(iterator)
        except StopIteration as exc:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected GET {url}") from exc
        if isinstance(r, BaseException):
            raise r
        return r

    return fake_get


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_normalize_endpoint_appends_slash():
    assert ac._normalize_endpoint("https://x.example/api") == "https://x.example/api/"
    assert ac._normalize_endpoint("https://x.example/api/") == "https://x.example/api/"


def test_normalize_endpoint_rejects_garbage():
    with pytest.raises(ac.APIError):
        ac._normalize_endpoint("")
    with pytest.raises(ac.APIError):
        ac._normalize_endpoint("not-a-url")


def test_qs_drops_none_values():
    out = ac._qs({"a": 1, "b": None, "c": "x"})
    assert "a=1" in out and "c=x" in out and "b=" not in out


def test_norm_room_filter():
    assert ac._normalize_room_filter(None) is None
    assert ac._normalize_room_filter("") is None
    assert ac._normalize_room_filter("#best") == "best"
    assert ac._normalize_room_filter("Best") == "best"


def test_flatten_event_resolves_ids():
    raw = {
        "id": "ev1",
        "eventIndex": 100,
        "createdAt": "2026-06-01T17:00:00Z",
        "data": {
            "actionType": "AGENT_TALK",
            "speakerId": "uuid-a",
            "speakerType": "agent",
            "roomId": "uuid-r",
            "content": "hello",
            "cost": 1,
            "inputTokens": 10,
            "outputTokens": 5,
        },
    }
    flat = ac._flatten_event(
        raw,
        agents={"uuid-a": "Claude Opus 4.7"},
        rooms={"uuid-r": "best"},
    )
    assert flat["agent_name"] == "Claude Opus 4.7"
    assert flat["room"] == "best"
    assert flat["room_id"] == "uuid-r"
    assert flat["action_type"] == "AGENT_TALK"
    assert flat["content"] == "hello"
    assert flat["event_index"] == 100
    assert flat["cost"] == 1


def test_flatten_event_unknown_speaker_uses_name_fallback():
    raw = {
        "id": "ev2",
        "data": {
            "actionType": "USER_TALK",
            "userName": "admin",
            "content": "hi all",
        },
    }
    flat = ac._flatten_event(raw, agents={}, rooms={})
    assert flat["agent_name"] == "admin"
    assert flat["room"] is None


def test_flatten_event_consolidate_uses_next_session_goal_for_content():
    raw = {
        "id": "ev3",
        "data": {
            "actionType": "CONSOLIDATE",
            "speakerId": "u1",
            "nextSessionGoal": "carry on",
        },
    }
    flat = ac._flatten_event(raw, agents={"u1": "Kimi K2.6"}, rooms={})
    assert flat["agent_name"] == "Kimi K2.6"
    assert flat["action_type"] == "CONSOLIDATE"
    assert flat["content"] == "carry on"


# ---------------------------------------------------------------------------
# APIError surfacing
# ---------------------------------------------------------------------------


def test_apierror_4xx_does_not_retry():
    responses = [_FakeResp({"error": "bad"}, status=404, text='{"error":"bad"}')]
    with mock.patch.object(ac, "_requests") as fake_req:
        fake_req.get.side_effect = _fake_get_factory(responses)
        # mark as truthy "module" so _http_get_json takes the requests branch
        fake_req.__bool__ = lambda self: True  # type: ignore[assignment]
        with pytest.raises(ac.APIError) as ei:
            ac._http_get_json("https://x.example/foo", max_retries=3, backoff=0)
    assert ei.value.status == 404


def test_apierror_5xx_retries_then_succeeds():
    responses = [
        _FakeResp({"oops": True}, status=503, text="busy"),
        _FakeResp({"ok": True}, status=200),
    ]
    with mock.patch.object(ac, "_requests") as fake_req, \
         mock.patch.object(ac.time, "sleep"):
        fake_req.get.side_effect = _fake_get_factory(responses)
        out = ac._http_get_json("https://x.example/foo", max_retries=3, backoff=0)
    assert out == {"ok": True}


# ---------------------------------------------------------------------------
# Client behaviour (mocked)
# ---------------------------------------------------------------------------


def _client_with_responses(responses, *, village_id=None):
    """Build a client whose `_get` is patched to return queued payloads."""
    iterator = iter(responses)

    def fake_get(self, path, params=None):  # noqa: ARG001
        return next(iterator)

    c = ac.VillageAPIClient(village_id=village_id)
    with mock.patch.object(ac.VillageAPIClient, "_get", fake_get):
        yield c


def test_village_id_resolution(monkeypatch):
    responses = [{"id": "vid-1"}]
    iterator = iter(responses)
    monkeypatch.setattr(
        ac.VillageAPIClient,
        "_get",
        lambda self, path, params=None: next(iterator),
    )
    c = ac.VillageAPIClient()
    assert c.village_id == "vid-1"
    # cached on second access
    assert c.village_id == "vid-1"


def test_village_id_resolution_failure(monkeypatch):
    monkeypatch.setattr(
        ac.VillageAPIClient,
        "_get",
        lambda self, path, params=None: {"error": "Village not found"},
    )
    c = ac.VillageAPIClient()
    with pytest.raises(ac.APIError):
        c.village_id  # noqa: B018


def test_get_agents_and_rooms(monkeypatch):
    village_detail = {
        "id": "vid-1",
        "createdAt": "2025-04-02T17:45:08Z",
        "agents": [
            {"id": "a1", "name": "Alpha"},
            {"id": "a2", "name": "Beta"},
        ],
        "activeAgent": {"id": "a3", "name": "Gamma"},
        "chatRooms": [
            {"id": "r1", "name": "best"},
            {"id": "r2", "name": "rest"},
        ],
    }
    monkeypatch.setattr(
        ac.VillageAPIClient,
        "_get",
        lambda self, path, params=None: village_detail,
    )
    c = ac.VillageAPIClient(village_id="vid-1")
    assert c.get_agents() == {"a1": "Alpha", "a2": "Beta", "a3": "Gamma"}
    assert c.get_rooms() == {"r1": "best", "r2": "rest"}


def test_iter_raw_events_for_day_paginates(monkeypatch):
    pages = [
        {"events": [{"id": "e1", "eventIndex": 1, "data": {}}], "hasMore": True},
        {"events": [{"id": "e2", "eventIndex": 2, "data": {}}], "hasMore": False},
    ]
    iterator = iter(pages)
    monkeypatch.setattr(
        ac.VillageAPIClient,
        "_get",
        lambda self, path, params=None: next(iterator),
    )
    c = ac.VillageAPIClient(village_id="vid-1")
    ids = [e["id"] for e in c.iter_raw_events_for_day(day=426)]
    assert ids == ["e1", "e2"]


def test_fetch_events_filters_and_sorts(monkeypatch):
    village_detail = {
        "id": "vid-1",
        "createdAt": "2025-04-02T17:45:08Z",
        "agents": [
            {"id": "a1", "name": "Claude Opus 4.7"},
            {"id": "a2", "name": "Kimi K2.6"},
        ],
        "chatRooms": [
            {"id": "r1", "name": "best"},
            {"id": "r2", "name": "rest"},
        ],
    }
    events_page = {
        "events": [
            {
                "id": "e2",
                "eventIndex": 200,
                "createdAt": "2026-06-01T18:00:00Z",
                "data": {
                    "actionType": "AGENT_TALK",
                    "speakerId": "a2",
                    "roomId": "r1",
                    "content": "later",
                },
            },
            {
                "id": "e1",
                "eventIndex": 100,
                "createdAt": "2026-06-01T17:00:00Z",
                "data": {
                    "actionType": "AGENT_TALK",
                    "speakerId": "a1",
                    "roomId": "r1",
                    "content": "earlier",
                },
            },
            {
                "id": "e3",
                "eventIndex": 150,
                "createdAt": "2026-06-01T17:30:00Z",
                "data": {
                    "actionType": "PAUSE",
                    "speakerId": "a1",
                    "roomId": "r2",
                    "content": "",
                },
            },
        ],
        "hasMore": False,
    }
    queue = [village_detail, events_page]
    iterator = iter(queue)

    def fake_get(self, path, params=None):  # noqa: ARG001
        return next(iterator)

    monkeypatch.setattr(ac.VillageAPIClient, "_get", fake_get)
    monkeypatch.setattr(
        ac.VillageAPIClient, "_discover_latest_day", lambda self: 426
    )

    c = ac.VillageAPIClient(village_id="vid-1")
    out = c.fetch_events(days=1, room="best")
    # Two best events, oldest-first
    assert [e["event_index"] for e in out] == [100, 200]
    assert all(e["room"] == "best" for e in out)

    # Filter by agent (case-insensitive substring) - cache means only the
    # events page is fetched the second time.
    nonlocal_iter = iter([events_page])
    def fake_get2(self, path, params=None):
        return next(nonlocal_iter)
    monkeypatch.setattr(ac.VillageAPIClient, "_get", fake_get2)
    out = c.fetch_events(days=1, agent="kimi")
    assert [e["agent_name"] for e in out] == ["Kimi K2.6"]


def test_fetch_events_action_types_filter(monkeypatch):
    village_detail = {
        "id": "vid-1",
        "createdAt": "2025-04-02T17:45:08Z",
        "agents": [{"id": "a1", "name": "X"}],
        "chatRooms": [{"id": "r1", "name": "best"}],
    }
    events_page = {
        "events": [
            {"id": "e1", "eventIndex": 1, "createdAt": "2026-06-01T17:00:00Z",
             "data": {"actionType": "AGENT_TALK", "speakerId": "a1", "roomId": "r1", "content": "x"}},
            {"id": "e2", "eventIndex": 2, "createdAt": "2026-06-01T17:00:01Z",
             "data": {"actionType": "PAUSE", "speakerId": "a1", "roomId": "r1", "content": ""}},
        ],
        "hasMore": False,
    }
    iterator = iter([village_detail, events_page])
    monkeypatch.setattr(
        ac.VillageAPIClient, "_get",
        lambda self, path, params=None: next(iterator),
    )
    monkeypatch.setattr(
        ac.VillageAPIClient, "_discover_latest_day", lambda self: 426
    )
    c = ac.VillageAPIClient(village_id="vid-1")
    out = c.fetch_events(days=1, action_types=["agent_talk"])
    assert [e["action_type"] for e in out] == ["AGENT_TALK"]


def test_fetch_events_module_level(monkeypatch):
    """``fetch_events`` (function) should delegate to a fresh client."""
    captured: dict = {}

    class FakeClient:
        def __init__(self, *, endpoint, village_slug, village_id):
            captured["endpoint"] = endpoint
            captured["village_slug"] = village_slug

        def fetch_events(self, **kwargs):
            captured["kwargs"] = kwargs
            return [{"ok": True}]

    monkeypatch.setattr(ac, "VillageAPIClient", FakeClient)
    out = ac.fetch_events(days=3, room="#best", agent="kimi")
    assert out == [{"ok": True}]
    assert captured["kwargs"] == {
        "days": 3, "room": "#best", "agent": "kimi", "action_types": None,
    }


# ---------------------------------------------------------------------------
# live smoke (opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("VILLAGE_PULSE_LIVE") != "1",
    reason="set VILLAGE_PULSE_LIVE=1 to run the live smoke test",
)

# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------

def test_norm_none_returns_empty_string():
    assert ac._norm(None) == ""

def test_flatten_event_non_string_content():
    raw = {
        "id": "ev4",
        "data": {
            "actionType": "CONSOLIDATE",
            "speakerId": "a1",
            "nextSessionGoal": 12345,
        }
    }
    flat = ac._flatten_event(raw, agents={"a1": "X"}, rooms={})
    assert flat["content"] == "12345"

def test_http_get_json_urllib_fallback():
    with mock.patch.object(ac, "_requests", None), \
         mock.patch("urllib.request.urlopen") as mock_urlopen:
        mock_fh = mock.MagicMock()
        mock_fh.read.return_value = b"{\"fallback\": true}"
        mock_fh.__enter__.return_value = mock_fh
        mock_urlopen.return_value = mock_fh
        
        out = ac._http_get_json("https://x.example/foo")
        assert out == {"fallback": True}

def test_http_get_json_urllib_fallback_invalid_json():
    with mock.patch.object(ac, "_requests", None), \
         mock.patch("urllib.request.urlopen") as mock_urlopen:
        mock_fh = mock.MagicMock()
        mock_fh.read.return_value = b"{\"fallback\": invalid"
        mock_fh.__enter__.return_value = mock_fh
        mock_urlopen.return_value = mock_fh
        
        with pytest.raises(ac.APIError):
            ac._http_get_json("https://x.example/foo")

def test_iter_raw_events_for_day_returns_early():
    c = ac.VillageAPIClient(village_id="vid-1")
    with mock.patch.object(c, "_get", return_value={}):
        assert list(c.iter_raw_events_for_day(day=426)) == []

def test_discover_latest_day_no_created_at():
    c = ac.VillageAPIClient(village_id="vid-1")
    with mock.patch.object(c, "get_village", return_value={}):
        assert c._discover_latest_day() is None


def test_live_smoke():
    c = ac.VillageAPIClient()
    assert c.village_id
    assert c.get_agents()
    assert c.get_rooms()
    evs = c.fetch_events(days=1)
    assert isinstance(evs, list)


def test_http_get_json_requests_value_error():
    with mock.patch.object(ac, "_requests") as fake_req:
        fake_req.__bool__ = lambda self: True
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"bad": json}'
        mock_resp.json.side_effect = ValueError("JSON decode error")
        fake_req.get.return_value = mock_resp
        with pytest.raises(ac.APIError) as exc_info:
            ac._http_get_json("https://x.example/foo")
        assert "invalid JSON" in str(exc_info.value)


def test_fetch_events_latest_day_none(monkeypatch):
    village_detail = {
        "id": "vid-1",
        "createdAt": "2025-04-02T17:45:08Z",
        "agents": [],
        "chatRooms": [],
    }
    events_page = {"events": [], "hasMore": False}
    iterator = iter([village_detail, events_page])
    monkeypatch.setattr(
        ac.VillageAPIClient, "_get",
        lambda self, path, params=None: next(iterator)
    )
    monkeypatch.setattr(
        ac.VillageAPIClient, "_discover_latest_day", lambda self: None
    )
    c = ac.VillageAPIClient(village_id="vid-1")
    out = c.fetch_events(days=1)
    assert out == []


def test_normalize_room_filter_empty_normalization():
    assert ac._normalize_room_filter("#") is None
    assert ac._normalize_room_filter("   ") is None
