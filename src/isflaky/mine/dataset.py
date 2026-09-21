import json
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from isflaky.core.models import Failure, Label, LabeledFailure, Provenance
from isflaky.mine.github import GitHubClient, WorkflowRun
from isflaky.mine.label import label_attempt_pair

_MAX_WORKERS = 8


def write_dataset(records: Iterable[LabeledFailure], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(
                json.dumps(
                    {
                        "failure": asdict(record.failure),
                        "label": record.label.value,
                        "provenance": asdict(record.provenance),
                    }
                )
                + "\n"
            )
            count += 1
    return count


def read_dataset(path: Path) -> list[LabeledFailure]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            records.append(
                LabeledFailure(
                    failure=Failure(**raw["failure"]),
                    label=Label(raw["label"]),
                    provenance=Provenance(**raw["provenance"]),
                )
            )
    return records


def read_seen_runs(path: Path) -> dict[str, set[int]]:
    """Run ids already downloaded, whether or not they produced a label."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {repo: set(run_ids) for repo, run_ids in raw.items()}


def write_seen_runs(path: Path, seen: dict[str, set[int]]) -> None:
    merged = read_seen_runs(path)
    for repo, run_ids in seen.items():
        merged.setdefault(repo, set()).update(run_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({repo: sorted(run_ids) for repo, run_ids in merged.items()}),
        encoding="utf-8",
    )


def _mine_pair(
    client: GitHubClient, repo: str, run: WorkflowRun, attempt: int
) -> list[LabeledFailure]:
    log_a = client.attempt_log(repo, run.run_id, attempt)
    log_b = client.attempt_log(repo, run.run_id, attempt + 1)
    if not log_a or not log_b:
        return []
    return label_attempt_pair(run, attempt, log_a, log_b)


def mine_repo(
    client: GitHubClient,
    repo: str,
    skip_run_ids: frozenset[int] = frozenset(),
    examined: set[int] | None = None,
) -> Iterator[LabeledFailure]:
    runs = [r for r in client.failed_runs_with_reruns(repo) if r.run_id not in skip_run_ids]
    pairs = [(run, attempt) for run in runs for attempt in range(1, run.attempts)]
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {
            pool.submit(_mine_pair, client, repo, run, attempt): run.run_id
            for run, attempt in pairs
        }
        for future in as_completed(futures):
            if examined is not None:
                examined.add(futures[future])
            yield from future.result()
