import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from isflaky.mine.github import GitHubClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "api"


def make_log_zip(content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("0_build.txt", content)
    return buffer.getvalue()


def make_client(handler) -> GitHubClient:
    return GitHubClient(token="fake", transport=httpx.MockTransport(handler))


def make_paging_handler(payload):
    """Serves the fixture page once, then an empty page, so pagination stops."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        if page == "1":
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"workflow_runs": []})

    return handler


def test_keeps_only_runs_that_were_rerun():
    payload = json.loads((FIXTURES / "runs_page.json").read_text())
    runs = make_client(make_paging_handler(payload)).failed_runs_with_reruns("acme/proj")
    assert [run.run_id for run in runs] == [101, 103]


def test_run_carries_sha_attempts_and_repo():
    payload = json.loads((FIXTURES / "runs_page.json").read_text())
    runs = make_client(make_paging_handler(payload)).failed_runs_with_reruns("acme/proj")
    assert runs[0].head_sha == "aaa111"
    assert runs[0].attempts == 2
    assert runs[0].repo == "acme/proj"


def test_attempt_log_unzips_and_concatenates_members():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=make_log_zip("FAILED tests/a.py::test_x - boom"))

    text = make_client(handler).attempt_log("acme/proj", 101, 1)
    assert "FAILED tests/a.py::test_x" in text


def test_expired_log_returns_empty_string():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(410)

    assert make_client(handler).attempt_log("acme/proj", 101, 1) == ""


def test_missing_log_returns_empty_string():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    assert make_client(handler).attempt_log("acme/proj", 101, 1) == ""


def test_pagination_continues_until_an_empty_page():
    page_one = {
        "workflow_runs": [
            {"id": 1, "head_sha": "s1", "run_attempt": 2, "html_url": "https://example.test/1"}
        ]
    }
    page_two = {
        "workflow_runs": [
            {"id": 2, "head_sha": "s2", "run_attempt": 2, "html_url": "https://example.test/2"}
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        if page == "1":
            return httpx.Response(200, json=page_one)
        if page == "2":
            return httpx.Response(200, json=page_two)
        return httpx.Response(200, json={"workflow_runs": []})

    runs = make_client(handler).failed_runs_with_reruns("acme/proj")
    assert [run.run_id for run in runs] == [1, 2]


def test_transport_error_returns_empty_string():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("peer closed connection")

    assert make_client(handler).attempt_log("acme/proj", 101, 1) == ""


def test_corrupt_zip_returns_empty_string():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not a zip file")

    assert make_client(handler).attempt_log("acme/proj", 101, 1) == ""


def test_stops_paginating_once_runs_are_older_than_the_cutoff():
    """Logs expire long before runs leave the API, so old pages are dead weight."""
    fresh = {
        "workflow_runs": [
            {
                "id": 1,
                "head_sha": "s1",
                "run_attempt": 2,
                "created_at": "2026-09-20T00:00:00Z",
                "html_url": "https://example.test/1",
            }
        ]
    }
    stale = {
        "workflow_runs": [
            {
                "id": 2,
                "head_sha": "s2",
                "run_attempt": 2,
                "created_at": "2026-01-01T00:00:00Z",
                "html_url": "https://example.test/2",
            }
        ]
    }
    pages_fetched = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        pages_fetched.append(page)
        return httpx.Response(200, json=fresh if page == "1" else stale)

    runs = make_client(handler).failed_runs_with_reruns(
        "acme/proj", max_age_days=30, now=datetime(2026, 9, 21, tzinfo=timezone.utc)
    )

    assert [run.run_id for run in runs] == [1]
    assert pages_fetched == ["1", "2"]


def test_runs_without_a_created_at_are_kept():
    payload = {
        "workflow_runs": [
            {"id": 7, "head_sha": "s7", "run_attempt": 2, "html_url": "https://example.test/7"}
        ]
    }
    runs = make_client(make_paging_handler(payload)).failed_runs_with_reruns("acme/proj")
    assert [run.run_id for run in runs] == [7]


def test_auth_error_is_not_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(httpx.HTTPStatusError):
        make_client(handler).failed_runs_with_reruns("acme/proj")
