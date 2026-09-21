import io
import json
import zipfile
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


def test_keeps_only_runs_that_were_rerun():
    payload = json.loads((FIXTURES / "runs_page.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    runs = make_client(handler).failed_runs_with_reruns("acme/proj")
    assert [run.run_id for run in runs] == [101, 103]


def test_run_carries_sha_attempts_and_repo():
    payload = json.loads((FIXTURES / "runs_page.json").read_text())
    runs = make_client(lambda request: httpx.Response(200, json=payload)).failed_runs_with_reruns(
        "acme/proj"
    )
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


def test_auth_error_is_not_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(httpx.HTTPStatusError):
        make_client(handler).failed_runs_with_reruns("acme/proj")
