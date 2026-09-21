import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from pathlib import Path

from isflaky.core.models import Failure, Label, LabeledFailure, Provenance
from isflaky.mine.github import GitHubClient
from isflaky.mine.label import label_attempt_pair


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


def mine_repo(client: GitHubClient, repo: str) -> Iterator[LabeledFailure]:
    for run in client.failed_runs_with_reruns(repo):
        for attempt in range(1, run.attempts):
            log_a = client.attempt_log(repo, run.run_id, attempt)
            log_b = client.attempt_log(repo, run.run_id, attempt + 1)
            if not log_a or not log_b:
                continue
            yield from label_attempt_pair(run, attempt, log_a, log_b)
