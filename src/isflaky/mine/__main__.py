import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from isflaky.mine.dataset import (
    mine_repo,
    read_dataset,
    read_seen_runs,
    write_dataset,
    write_seen_runs,
)
from isflaky.mine.github import GitHubClient


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="isflaky-mine")
    parser.add_argument("repos", nargs="+", help="owner/name")
    parser.add_argument("--out", type=Path, default=Path("data/dataset.jsonl"))
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 2

    existing = read_dataset(args.out) if args.out.exists() else []
    seen_path = args.out.with_name("seen_runs.json")
    seen = read_seen_runs(seen_path)

    client = GitHubClient(token=token)
    total = 0
    for repo in args.repos:
        skip = frozenset(
            {r.provenance.run_id for r in existing if r.provenance.repo == repo}
            | seen.get(repo, set())
        )
        examined: set[int] = set()
        written = write_dataset(
            mine_repo(client, repo, skip_run_ids=skip, examined=examined), args.out
        )
        write_seen_runs(seen_path, {repo: examined})
        total += written
        print(f"{repo}: {written} labeled failures ({len(skip)} runs skipped, {len(examined)} examined)")
    print(f"total: {total} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
