"""Unit tests for mastery_client.py's httpx calls: one success case and one
real failure case (timeout / connection error / non-2xx) per function, using
`httpx.MockTransport` - httpx's own built-in test transport, not a third-
party mocking library (nothing in this codebase already pulls one in - see
`backend/mastery/test_scenario.py`, the only other httpx-adjacent test file,
which doesn't mock httpx either). No real network calls happen in this file.

mastery_client.py constructs a fresh `httpx.AsyncClient(timeout=...)` inline
inside each function rather than taking one as a dependency, so the patch
point is `httpx.AsyncClient` itself (module-level, via monkeypatch) - the
patched class drops in `transport=httpx.MockTransport(handler)` and defers
everything else to the real AsyncClient, so `async with httpx.AsyncClient(...)
as client:` in the source keeps working unmodified.
"""

import httpx
import pytest

import mastery_client


def _patched_async_client(monkeypatch, handler):
    """Make every `httpx.AsyncClient(...)` constructed inside mastery_client
    route through `httpx.MockTransport(handler)` instead of the network."""

    class _MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(mastery_client.httpx, "AsyncClient", _MockedAsyncClient)


# ---------------------------------------------------------------------------
# fetch_mastery_vector
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_mastery_vector_success_reshapes_rows_into_a_dict(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/students/demo-1/mastery"
        return httpx.Response(
            200,
            json=[
                {"skill_id": "vowel_teams", "weight": 0.4},
                {"skill_id": "consonant_blends", "weight": 0.8},
            ],
        )

    _patched_async_client(monkeypatch, handler)

    result = await mastery_client.fetch_mastery_vector("demo-1")

    assert result == {"vowel_teams": 0.4, "consonant_blends": 0.8}


@pytest.mark.asyncio
async def test_fetch_mastery_vector_returns_none_without_a_student_id():
    """No student id (mastery service unreachable earlier in the flow) means
    no call is even attempted."""
    assert await mastery_client.fetch_mastery_vector(None) is None


@pytest.mark.asyncio
async def test_fetch_mastery_vector_timeout_falls_back_to_none(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    _patched_async_client(monkeypatch, handler)

    result = await mastery_client.fetch_mastery_vector("demo-1")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_mastery_vector_connection_error_falls_back_to_none(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patched_async_client(monkeypatch, handler)

    result = await mastery_client.fetch_mastery_vector("demo-1")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_mastery_vector_non_2xx_falls_back_to_none(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal"})

    _patched_async_client(monkeypatch, handler)

    result = await mastery_client.fetch_mastery_vector("demo-1")

    assert result is None


# ---------------------------------------------------------------------------
# fetch_next_passage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_next_passage_success_returns_service_passage_and_student_id(monkeypatch):
    passage = {"id": "g2-blends-003", "title": "A Story", "words": ["a"]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/students/demo-1/next_passage":
            return httpx.Response(200, json=passage)
        raise AssertionError(f"unexpected path {request.url.path}")

    _patched_async_client(monkeypatch, handler)

    result_passage, student_id = await mastery_client.fetch_next_passage(
        None, student_id_override="demo-1"
    )

    assert result_passage == passage
    assert student_id == "demo-1"


@pytest.mark.asyncio
async def test_fetch_next_passage_service_failure_falls_back_to_local_passage(monkeypatch):
    """A real failure (service down/errors) must not crash a live session -
    it falls back to the bundled local default passage, still reporting the
    student id it did resolve (per the function's own docstring: a demo
    student can't get mastery-enriched data from a service that isn't
    running either way, but the id itself came from a separate call)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    _patched_async_client(monkeypatch, handler)

    result_passage, student_id = await mastery_client.fetch_next_passage(
        None, student_id_override="demo-1"
    )

    assert student_id == "demo-1"
    assert result_passage["id"] == mastery_client._DEFAULT_PASSAGE_ID


@pytest.mark.asyncio
async def test_fetch_next_passage_with_no_student_uses_local_fallback_immediately(monkeypatch):
    """No student id resolvable at all (mastery service unreachable for the
    demo-student lookup too) - falls back to the local passage without
    attempting the passage call, and reports student_id=None."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patched_async_client(monkeypatch, handler)

    result_passage, student_id = await mastery_client.fetch_next_passage(None, None)

    assert student_id is None
    assert result_passage["id"] == mastery_client._DEFAULT_PASSAGE_ID


# ---------------------------------------------------------------------------
# post_completed_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_completed_session_success_posts_expected_payload_and_returns_session_id(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content
        # Real shape of backend/mastery/main.py's IngestSessionResponse -
        # session_id is always present in a real /sessions response,
        # confirmed via live curl testing (see this function's own
        # docstring for why tutor_processor.py needs this back).
        return httpx.Response(200, json={"session_id": "session-1", "updates": []})

    _patched_async_client(monkeypatch, handler)

    result = await mastery_client.post_completed_session(
        student_id="demo-1",
        passage_id="g1-short-vowels-001",
        session_columns={"wcpm": 58.2, "accuracy": 0.91, "self_corrections": 2},
    )

    assert result == "session-1"
    assert captured["path"] == "/sessions"
    import json as _json

    body = _json.loads(captured["body"])
    assert body["student_id"] == "demo-1"
    assert body["passage_id"] == "g1-short-vowels-001"
    assert body["wcpm"] == 58.2
    assert body["accuracy"] == 0.91
    assert body["self_corrections"] == 2


@pytest.mark.asyncio
async def test_post_completed_session_failure_is_swallowed_not_raised(monkeypatch):
    """Best-effort per the module docstring: a bookkeeping failure after the
    child's session already finished must not raise back into the live
    pipeline - this call should return normally either way."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    _patched_async_client(monkeypatch, handler)

    # Must not raise, and must report "no id" rather than a stale/fake one -
    # tutor_processor.py's session_ended event needs to know persistence
    # didn't happen.
    result = await mastery_client.post_completed_session(
        student_id="demo-1", passage_id="g1-short-vowels-001", session_columns={}
    )
    assert result is None


@pytest.mark.asyncio
async def test_post_completed_session_non_2xx_is_swallowed_not_raised(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    _patched_async_client(monkeypatch, handler)

    # Must not raise.
    result = await mastery_client.post_completed_session(
        student_id="demo-1", passage_id="g1-short-vowels-001", session_columns={}
    )
    assert result is None
