# Plan 2: Decision engine, gate, and benchmark

Plan 1 produced a labeled dataset.
This plan turns it into published numbers.

The deliverable is a benchmark that can answer three questions with evidence:
does Jev beat a free regex baseline, does it beat a small LLM, and is its confidence calibrated.
If the regex baseline wins, the project's premise collapses, and spec section 12 requires us to discover that here rather than let a reader discover it.

Everything below follows the spec's architecture in section 9.
The load-bearing constraint is that the CLI and the benchmark run the same code path, so the benchmark swaps the source of failures and the model implementation, never the pipeline.

## Prerequisites

The dataset from Plan 1 exists at `data/dataset.jsonl`.
Its size is modest, because GitHub expires Actions log artifacts far sooner than the spec assumed.
Section 18's threshold of 1,000 pairs is not met, so every published number in this plan carries a confidence interval and the README states the sample size plainly.
That is the honest response to a small sample, and it is a better portfolio artifact than a large number with a hidden caveat.

## Task 1: Install the TypeSafe SDK and confirm the API shape

The spec assumes `Noul` returns a probability and `Score` returns a level.
No code should be written against that assumption until it is verified against the live API.

**Step 1.** Add the `llm` and `bench` extras to `pyproject.toml`:

```toml
[project.optional-dependencies]
mine = ["httpx>=0.27", "python-dotenv>=1.0"]
llm = ["groq>=0.11"]
bench = ["numpy>=1.26", "scipy>=1.11"]
```

Add `typesafe-sdk` to the base dependencies, because the engine is not optional.

**Step 2.** Run `uv sync --extra llm --extra bench --reinstall-package isflaky`.

**Step 3.** Write a throwaway probe that sends one trivial `Noul` question and prints the raw response object.
Confirm the field names, the probability range, and whether confidence is returned separately from probability.
Record what the response actually looks like.

**Step 4.** Delete the probe. Commit only the dependency change.

If the SDK does not behave as the spec assumes, stop and report the discrepancy before continuing.
The rest of this plan depends on it.

## Task 2: Core answer and verdict types

`core/models.py` already holds `Failure`, `Label`, and `Provenance`.
Add the types the engine and gate exchange.

**Step 1.** Write `tests/core/test_answers.py` asserting that `Answers` carries a mapping of question name to value, that `Verdict` carries a label, a probability, a confidence, a cause line, and a reason string, and that both are frozen.

**Step 2.** Verify the test fails.

**Step 3.** Add to `core/models.py`:

```python
@dataclass(frozen=True)
class Answers:
    values: Mapping[str, float]
    latency_ms: float
    truncated: bool


@dataclass(frozen=True)
class Verdict:
    label: Label
    probability: float
    confidence: float
    cause: str
    reason: str
    escalated: bool
```

`escalated` is separate from `label` because spec section 7.1 requires an escalated verdict to be visually distinct, and section 7.3 maps uncertainty to exit code 1 regardless of which label was chosen.

**Step 4.** Verify the tests pass, then commit.

## Task 3: The question set loader

Question sets are configuration, not code.
Spec section 9.1 calls this the decisive architectural requirement, because comparing the direct design against the atomic design must be a config swap rather than a code branch.

**Step 1.** Write `tests/engine/test_questions.py` asserting that a YAML file loads into a `QuestionSet` carrying a name and an ordered list of questions, each with a name, a kind of either `noul` or `score`, and a prompt; and that an unknown kind raises.

**Step 2.** Verify the test fails.

**Step 3.** Write `engine/questions.py` with a `Question` dataclass, a `QuestionSet` dataclass, and `load_question_set(name_or_path) -> QuestionSet` that resolves a bare name against the packaged `engine/questions/` directory.

**Step 4.** Write `engine/questions/direct.yaml` with the single `Noul` from spec section 11.1, and `engine/questions/atomic.yaml` with the eight questions from section 11.2.

**Step 5.** Verify the tests pass, then commit.

## Task 4: The DecisionModel protocol and the heuristic implementation

The heuristic comes first because it needs no network and no key, which means every later test can use it.

**Step 1.** Write `tests/engine/test_contract.py` as a contract suite parameterized over model implementations, asserting that `decide` returns an `Answers` whose keys exactly match the question set's question names, and whose values are all within 0.0 to 1.0.
Spec section 14 requires this one suite to run against all three implementations.

**Step 2.** Verify it fails.

**Step 3.** Write `engine/protocol.py`:

```python
class DecisionModel(Protocol):
    def decide(self, state: Mapping[str, str], questions: QuestionSet) -> Answers: ...
```

**Step 4.** Write `engine/heuristic.py` implementing regex matching over the terms named in spec section 12: timeout, connection, reset, flake, and the resource and import terms from the atomic question set.
A question with no matching rule answers 0.5, which is the honest answer for a signal the heuristic cannot see.

**Step 5.** Register the heuristic in the contract suite. Verify the tests pass, then commit.

## Task 5: The Jev implementation

**Step 1.** Write `tests/engine/test_jev.py` using a recorded response fixture, asserting that questions are sent in one batched call, that the returned `Answers` maps question names to probabilities, and that a state exceeding the 32k budget is marked `truncated` rather than silently cut.

**Step 2.** Verify it fails.

**Step 3.** Write `engine/jev.py` against the API shape confirmed in Task 1.
All questions run in parallel over one state read, per spec section 11.2.

**Step 4.** Add it to the contract suite, backed by the fixture so the suite still runs with no key.

**Step 5.** Verify the tests pass, then commit.

## Task 6: The Groq baseline

**Step 1.** Write `tests/engine/test_groq.py` with a recorded fixture, asserting that a refusal or unparseable reply yields 0.5 for that question rather than raising, because one bad answer must not abort a benchmark run of hundreds.

**Step 2.** Verify it fails.

**Step 3.** Write `engine/groq.py` using `llama-3.1-8b-instant` by default and accepting `llama-3.3-70b-versatile` as an override, per spec section 12.
Ask for a probability, parse it strictly, and fall back to 0.5 on anything unparseable.

**Step 4.** Add it to the contract suite. Verify the tests pass, then commit.

## Task 7: The gate

The gate is deterministic, makes no network calls, and holds all asymmetric-cost policy.
It is the one component that can be fully tested with no model present.

**Step 1.** Write `tests/gate/test_gate.py` as table-driven tests across thresholds and cost ratios, asserting that a probability above the flaky threshold with sufficient confidence yields a non-escalated FLAKY verdict; that low confidence escalates regardless of probability; and that an escalated verdict never reports "safe to rerun".
Spec section 7.3 makes the last one a hard requirement.

**Step 2.** Verify it fails.

**Step 3.** Write `gate/policy.py` with `decide(answers, questions, thresholds) -> Verdict`, combining atomic answers into a single probability, deriving the reason string from the answers that moved the decision, and applying the escalation rule.

**Step 4.** Verify the tests pass, then commit.

## Task 8: Benchmark metrics

Spec section 14 requires the metrics to be tested on synthetic data with known answers before they are trusted on real data: a perfect model must score 1.0, a random model about 0.5, and a deliberately miscalibrated model must be caught by the calibration metrics.
If a miscalibrated model passes, the metrics are broken and every number built on them is false.

**Step 1.** Write `tests/bench/test_metrics.py` with those three synthetic models.

**Step 2.** Verify it fails.

**Step 3.** Write `bench/metrics.py` with accuracy, per-class precision and recall, Expected Calibration Error, Brier score, and bootstrap confidence intervals on each.

**Step 4.** Verify the tests pass, then commit.

## Task 9: The benchmark runner

**Step 1.** Write `tests/bench/test_runner.py` asserting that the runner produces one result row per dataset record per model, and that a model raising on one record does not abort the run.

**Step 2.** Verify it fails.

**Step 3.** Write `bench/runner.py`, reusing `collapse` and the gate exactly as the CLI will.
Spec section 9.3 is explicit that a benchmark measuring a different path than production reports numbers that are quietly false.

**Step 4.** Add McNemar's test for Jev against each baseline, per spec section 12.

**Step 5.** Verify the tests pass, then commit.

## Task 10: Run the benchmark and publish the numbers

**Step 1.** Run all models against both question sets over the full dataset.

**Step 2.** Report to the user: accuracy per model, ECE per model, the McNemar result for Jev against the regex baseline, and which question set won.

**Step 3.** Write `docs/benchmark.md` with the numbers, the confidence intervals, the sample size, and the dataset's known limitations stated plainly, including the log-retention finding from Plan 1.

**Step 4.** Commit the results.

If the regex baseline matches Jev, say so in the report.
That result is publishable and honest, and hiding it would be the one failure this project cannot recover from.

## Plan complete

Plan 3 adds the user-facing CLI, which is thin once the engine and gate exist: argument parsing, the output format from spec section 7.1, and the exit codes from section 7.3.
