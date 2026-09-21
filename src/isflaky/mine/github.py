import io
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

_API = "https://api.github.com"
# Log artifacts disappear well before runs leave the API, so runs older than
# this are almost always unminable and paginating into them wastes requests.
_MAX_AGE_DAYS = 30
# Actions log retention defaults to 90 days, but expired/missing logs answer
# either 410 or 404 depending on how far past retention they are.
_EXPIRED = {404, 410}


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

    def failed_runs_with_reruns(
        self,
        repo: str,
        max_pages: int = 15,
        max_age_days: int = _MAX_AGE_DAYS,
        now: datetime | None = None,
    ) -> list[WorkflowRun]:
        # status=failure would keep only runs whose LATEST attempt failed, which
        # drops exactly the fail-then-pass reruns the flaky label depends on.
        # List every run and filter on run_attempt instead.
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max_age_days)
        reruns: list[WorkflowRun] = []
        for page in range(1, max_pages + 1):
            response = self._client.get(
                f"/repos/{repo}/actions/runs",
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            runs = response.json()["workflow_runs"]
            if not runs:
                break
            reruns.extend(
                WorkflowRun(
                    run_id=run["id"],
                    head_sha=run["head_sha"],
                    attempts=run["run_attempt"],
                    url=run["html_url"],
                    repo=repo,
                )
                for run in runs
                if run["run_attempt"] > 1 and _created_at(run) >= cutoff
            )
            # Runs come back newest first, so once a whole page predates the
            # cutoff every later page does too.
            if all(_created_at(run) < cutoff for run in runs):
                break
        return reruns

    def attempt_log(self, repo: str, run_id: int, attempt: int) -> str:
        try:
            response = self._client.get(
                f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/logs"
            )
        except (httpx.TransportError, httpx.HTTPError):
            return ""
        if response.status_code in _EXPIRED:
            return ""
        try:
            response.raise_for_status()
            return _read_zip(response.content)
        except (httpx.HTTPError, zipfile.BadZipFile):
            return ""


def _created_at(run: dict[str, object]) -> datetime:
    """A run with no timestamp is treated as current, so it is never dropped."""
    raw = run.get("created_at")
    if not isinstance(raw, str):
        return datetime.max.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _read_zip(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [
            archive.read(name).decode("utf-8", errors="replace")
            for name in archive.namelist()
            if name.endswith(".txt")
        ]
    return "\n".join(members)
