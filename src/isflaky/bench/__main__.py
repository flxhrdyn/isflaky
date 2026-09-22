"""Run every available model over the dataset, fit the gate, and report.

Models whose API key is absent are skipped rather than faked, and the report
names which ones ran. `--replay` re-analyses a saved result file, so fitting
and reporting cost no further API calls.
"""

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from isflaky.bench.metrics import accuracy, confidence_interval, evaluate
from isflaky.bench.runner import McNemar, Row, mcnemar, run
from isflaky.bench.sweep import Operating, regate, split, sweep
from isflaky.core.models import Label, LabeledFailure
from isflaky.engine.heuristic import HeuristicModel
from isflaky.engine.protocol import DecisionModel
from isflaky.engine.questions import load_question_set
from isflaky.gate.policy import Thresholds
from isflaky.mine.dataset import read_dataset

_QUESTION_SETS = ("direct", "atomic")
_BASELINE = "regex"


def available_models() -> dict[str, DecisionModel]:
    models: dict[str, DecisionModel] = {_BASELINE: HeuristicModel()}
    jev_key = os.environ.get("TYPESAFE_API_KEY")
    if jev_key:
        from isflaky.engine.jev import JevModel

        models["jev"] = JevModel(api_key=jev_key)
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        from isflaky.engine.groq import GroqModel

        models["groq"] = GroqModel(api_key=groq_key)
    return models


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="isflaky-bench")
    parser.add_argument("--dataset", type=Path, default=Path("data/dataset.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("data/results.jsonl"))
    parser.add_argument(
        "--replay",
        type=Path,
        default=None,
        help="re-analyse saved rows instead of calling any model",
    )
    parser.add_argument("--cost-ratio", type=float, default=4.0)
    parser.add_argument("--confidence", type=float, default=0.6)
    args = parser.parse_args()

    if args.replay:
        rows = read_results(args.replay)
        print(f"replaying {len(rows)} rows from {args.replay}")
    else:
        dataset = read_dataset(args.dataset)
        models = available_models()
        print(f"dataset: n={len(dataset)}  {_majority(dataset)}")
        print(f"models: {', '.join(models)}")
        rows = [
            row
            for name in _QUESTION_SETS
            for row in run(
                dataset, models, load_question_set(name), Thresholds(flaky=0.5)
            )
        ]
        _write(args.out, rows)
        print(f"wrote {len(rows)} rows to {args.out}")

    fit, holdout = split(rows)
    print(
        f"\nsplit: fit={len({r.test_id for r in fit})} records, "
        f"holdout={len({r.test_id for r in holdout})} records, "
        f"cost_ratio={args.cost_ratio}\n"
    )
    for question_set in sorted({row.question_set for row in rows}):
        _report(question_set, fit, holdout, args.cost_ratio, args.confidence)
    return 0


def read_results(path: Path) -> list[Row]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            raw["truth"] = Label(raw["truth"])
            raw["predicted"] = Label(raw["predicted"])
            rows.append(Row(**raw))
    return rows


def _report(
    question_set: str,
    fit: Sequence[Row],
    holdout: Sequence[Row],
    cost_ratio: float,
    confidence: float,
) -> None:
    print(f"== {question_set} ==")
    models = sorted({row.model for row in fit})
    reported: dict[str, list[Row]] = {}

    for name in models:
        fitted = sweep(_of(fit, question_set, name), cost_ratio)
        thresholds = Thresholds(flaky=fitted.threshold, confidence=confidence)
        rows = regate(_of(holdout, question_set, name), thresholds)
        reported[name] = rows
        _print_model(name, fitted, rows)

    for name in models:
        if name == _BASELINE:
            continue
        print(
            f"{'':9s} mcnemar {name} vs {_BASELINE}: "
            f"{_format(mcnemar(reported[name], reported[_BASELINE]))}"
        )
    print()


def _print_model(name: str, fitted: Operating, rows: Sequence[Row]) -> None:
    truth = [row.truth for row in rows]
    predicted = [row.predicted for row in rows]
    scores = [row.probability for row in rows]
    evaluation = evaluate(truth, predicted, scores)
    low, high = confidence_interval(accuracy, truth, predicted)
    escalated = sum(1 for row in rows if row.escalated)
    print(
        f"{name:9s} t={fitted.threshold:.2f} acc={evaluation.accuracy:.3f} "
        f"[{low:.3f}, {high:.3f}]  ece={evaluation.ece:.3f}  "
        f"brier={evaluation.brier:.3f}  escalated={escalated}/{len(rows)}"
    )
    for label, pair in evaluation.per_class.items():
        print(
            f"{'':9s}   {label.value:5s} precision={pair.precision:.3f} "
            f"recall={pair.recall:.3f}"
        )


def _of(rows: Sequence[Row], question_set: str, model: str) -> list[Row]:
    return [
        row for row in rows if row.question_set == question_set and row.model == model
    ]


def _format(result: McNemar) -> str:
    return (
        f"discordant={result.discordant} "
        f"({result.only_first_correct} vs {result.only_second_correct}) "
        f"p={result.p_value:.4f}"
    )


def _majority(dataset: Sequence[LabeledFailure]) -> str:
    flaky = sum(1 for item in dataset if item.label is Label.FLAKY)
    share = flaky / len(dataset) if dataset else 0.0
    return f"flaky={flaky} real={len(dataset) - flaky} majority-class={share:.3f}"


def _write(path: Path, rows: Sequence[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            record = asdict(row)
            record["truth"] = row.truth.value
            record["predicted"] = row.predicted.value
            handle.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
