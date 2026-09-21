import io
import zipfile
from dataclasses import dataclass

import httpx

_API = "https://api.github.com"
# Actions log retention defaults to 90 days; expired logs answer 410.
_EXPIRED = 410


@dataclass(frozen=True)
class WorkflowRun:
    run_id: int
    head_sha: str
    attempts: int
    url: str
    repo: str


class GitHubClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url=_API,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
            },
            transport=transport,
            timeout=60.0,
            follow_redirects=True,
        )

    def failed_runs_with_reruns(self, repo: str) -> list[WorkflowRun]:
        response = self._client.get(
            f"/repos/{repo}/actions/runs",
            params={"status": "failure", "per_page": 100},
        )
        response.raise_for_status()
        return [
            WorkflowRun(
                run_id=run["id"],
                head_sha=run["head_sha"],
                attempts=run["run_attempt"],
                url=run["html_url"],
                repo=repo,
            )
            for run in response.json()["workflow_runs"]
            if run["run_attempt"] > 1
        ]

    def attempt_log(self, repo: str, run_id: int, attempt: int) -> str:
        response = self._client.get(
            f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/logs"
        )
        if response.status_code == _EXPIRED:
            return ""
        response.raise_for_status()
        return _read_zip(response.content)


def _read_zip(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [
            archive.read(name).decode("utf-8", errors="replace")
            for name in archive.namelist()
            if name.endswith(".txt")
        ]
    return "\n".join(members)
