import io
import zipfile

import httpx

from isflaky.core.models import Failure, Label, LabeledFailure, Provenance
from isflaky.mine.dataset import mine_repo, read_dataset, write_dataset
from isflaky.mine.github import GitHubClient


def make_record(test_id: str, label: Label) -> LabeledFailure:
    return LabeledFailure(
        failure=Failure(test_id, "boom", "trace", "context", 12),
        label=label,
        provenance=Provenance("acme/proj", 101, 1, "aaa111", "https://example.test/101"),
    )


def test_roundtrip_preserves_every_field(tmp_path):
    path = tmp_path / "dataset.jsonl"
    written = write_dataset([make_record("tests/a.py::test_x", Label.FLAKY)], path)
    assert written == 1

    restored = read_dataset(path)
    assert restored[0].failure.test_id == "tests/a.py::test_x"
    assert restored[0].failure.traceback == "trace"
    assert restored[0].label is Label.FLAKY
    assert restored[0].provenance.head_sha == "aaa111"


def test_one_json_object_per_line(tmp_path):
    path = tmp_path / "dataset.jsonl"
    write_dataset(
        [make_record("tests/a.py::test_x", Label.FLAKY), make_record("tests/b.py::test_y", Label.REAL)],
        path,
    )
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_write_is_resumable_by_appending(tmp_path):
    path = tmp_path / "dataset.jsonl"
    write_dataset([make_record("tests/a.py::test_x", Label.FLAKY)], path)
    write_dataset([make_record("tests/b.py::test_y", Label.REAL)], path)
    assert len(read_dataset(path)) == 2


def _make_log_zip(content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("0_build.txt", content)
    return buffer.getvalue()


def test_mine_repo_skips_runs_already_in_skip_run_ids():
    runs_payload = {
        "workflow_runs": [
            {"id": 101, "head_sha": "aaa", "run_attempt": 2, "html_url": "https://x/101"},
            {"id": 202, "head_sha": "bbb", "run_attempt": 2, "html_url": "https://x/202"},
        ]
    }
    fail_log = (
        "=========================== short test summary info ============================\n"
        "FAILED tests/a.py::test_x - boom\n"
    )
    pass_log = "1 passed in 0.01s\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if "actions/runs/" in request.url.path and "attempts/1" in request.url.path:
            return httpx.Response(200, content=_make_log_zip(fail_log))
        if "actions/runs/" in request.url.path and "attempts/2" in request.url.path:
            return httpx.Response(200, content=_make_log_zip(pass_log))
        return httpx.Response(200, json=runs_payload if request.url.params.get("page", "1") == "1" else {"workflow_runs": []})

    client = GitHubClient(token="fake", transport=httpx.MockTransport(handler))
    records = list(mine_repo(client, "acme/proj", skip_run_ids=frozenset({101})))

    assert {r.provenance.run_id for r in records} == {202}
