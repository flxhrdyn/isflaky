# isflaky - Design Document and PRD

Date: 2026-09-21
Status: Approved for implementation planning
Author: Felix

## 1. Summary

`isflaky` is an open-source CLI that reads a failed pytest run and decides, per failing test, whether the failure is flaky or a real regression.
It is built on TypeSafe Jev, a System One model that returns typed, calibrated decisions instead of text.

Four tools already do roughly this job in the Jev ecosystem.
None of them publishes evidence that its classification is correct.
`isflaky` ships with a reproducible benchmark built on real CI failures whose labels are proven by rerun evidence, and that benchmark is the product's reason to exist.

The claim is not "this works".
The claim is "here is how well it works, here is where it breaks, and here is the command that reproduces both numbers on your machine".

## 2. Problem

A red CI run forces a developer into a guess.
Rerun it and hope, or stop and read a 40,000-line log.
Guessing wrong in one direction wastes twenty minutes.
Guessing wrong in the other direction merges a real regression, because the rerun happened to go green.

The costs are asymmetric, so the decision threshold matters more than raw accuracy.
A tool that is right 90% of the time but confidently wrong about real regressions is worse than no tool, because it converts a human's healthy suspicion into misplaced trust.

Existing tools in this space present a label and a probability with no measured basis for either.
The single competitor that reports numbers reports 100% accuracy on a 79-case corpus it built itself, which is not evidence.

## 3. Goals

- Classify pytest failures as flaky or real with measured, reproducible accuracy.
- Report calibration, not just accuracy, so the confidence number can be trusted or distrusted on evidence.
- Fit decision thresholds that account for the asymmetric cost of the two error directions.
- Make every published number reproducible by a third party with one command.
- State the limitations of the method in the README, prominently, rather than burying them.
- Be usable daily as a local CLI with no CI setup and no repository integration.

## 4. Non-goals

- Fixing flaky tests, quarantining them, or filing issues. The tool decides; the human or the CI config acts.
- Supporting frameworks other than pytest in v1.
- Running as a GitHub Action in v1.
- Any claim about failure classes other than flaky and real. Advisory classes ship, but are marked unmeasured.
- Replacing an LLM for tasks that need generated text. Jev generates none, by design.

## 5. Prior art and positioning

The Jev ecosystem passed roughly 250 public projects within six days of the model's launch on 2026-09-15.
CI and log triage is a well-occupied niche inside it.

| Project | What it does | Evidence published |
|---|---|---|
| `jev-axi` | Agent-ergonomic CLI; reads up to four failed jobs, reports likely root-cause line, category, and a flaky flag | None |
| `jev-code` | Splits a CI log into separate failures, groups duplicates, relates each to the diff | None |
| `jev-logtriage` | Six questions in one call, gates to suppress/watch/review/notify/page; on PyPI | None |
| `jevtriage` | GitHub Action and CLI; triages PRs as ready/needs-review/risky | None |
| `jev-audit` | Pre-commit auditor | 79-case self-built corpus at 100% |

Adjacent tooling worth interoperating with rather than duplicating:

- `jevcal` fits per-question confidence thresholds to an accuracy target with held-out verification and CI drift checks. It is mature and owns the general calibration problem. `isflaky` should reference it, not reimplement it.
- `jev-lab` and `jev-empirical` run perturbation and calibration experiments, but as one-off study repos rather than reusable tooling.

The differentiator is therefore not the feature.
It is the evidence, and the fact that the evidence is cheap to produce only because Jev costs $0.042 per million input tokens with free output.
Copying the feature takes an afternoon.
Copying the evidence requires building the labeled dataset and the evaluation harness, which is the expensive part.

## 6. Users and use cases

The primary user is a Python developer whose CI just went red, working locally.

```
$ pytest 2>&1 | tee build.log
$ isflaky run build.log
```

The secondary user is the same developer's CI, once a GitHub Action wrapper exists in a later version.

The third user, and the one who decides whether the project earns attention, is a reader evaluating whether the numbers are honest.
That reader must be able to run `make bench` and get the README's numbers back.

## 7. Product requirements

### 7.1 Primary command

```
$ isflaky run build.log

  tests/test_api.py::test_retry
  FLAKY  p=0.91  conf=0.88   above threshold - safe to rerun
  cause  L2841: ConnectionResetError: [Errno 104]
  why    network error present; no diff touching this module

  tests/test_auth.py::test_expiry
  REAL   p=0.76  conf=0.52   below threshold - human review
  cause  L3102: AssertionError: assert 1758412800 < 1758412800

  2 failures | 1 auto-classified | 1 escalated
```

Requirements:

- One decision per failing test, never one decision per log.
- Every verdict carries a probability, a calibrated confidence, and the log line identified as the cause.
- Every verdict carries a short reason derived from the atomic answers, so the user can disagree with the reasoning rather than only with the label.
- An escalated verdict must be visually distinct from a confident one.

### 7.2 Optional inputs

- `--diff <file>` supplies the change under test, which feeds the `touches_test_code` signal.
- `--questions <name|path>` selects the question set, defaulting to whichever wins the benchmark.
- `--threshold <float>` overrides the fitted gate.
- `--json` emits machine-readable output for scripting.

### 7.3 Exit codes

```
0  no real regression detected
1  real regression detected, OR confidence below the gate
2  tool error
```

Uncertainty maps to `1`, never to `0`.
The tool must never report "safe to rerun" when it does not know.
This follows directly from the asymmetric cost in section 2 and is a hard requirement, not a default.

### 7.4 Advisory classes

The tool additionally reports `infra`, `dependency`, `lint`, and `config` when the atomic answers indicate them.
These are printed with an explicit `advisory, unmeasured` marker, and the README states that no accuracy claim covers them.
They exist because they are useful daily; they are marked because no free ground truth source exists for them.

## 8. Ground truth methodology

This section is the foundation of every published number.
If it is wrong, nothing else in the project matters.

### 8.1 Label definition

Labels come only from rerun evidence at an identical commit SHA.

```
same head_sha, consecutive run attempts:

  attempt N FAIL -> attempt N+1 PASS   = flaky
  attempt N FAIL -> attempt N+1 FAIL   = real
  attempt N FAIL -> no rerun exists    = unlabeled, discarded
```

A failure that was never rerun is not a real regression.
It is unlabeled, and it is dropped.
Treating unlabeled failures as real would turn that class into a dumping ground holding infrastructure failures, dependency breakage, and flakes nobody happened to rerun, which would inflate apparent accuracy and destroy the project's only reason to exist.

### 8.2 Known limitation, disclosed

This definition introduces selection bias.
The dataset covers only failures that somebody chose to rerun, which skews toward failures that looked rerunnable to a human.
This is stated in the README next to the headline numbers, not in a footnote.

Disclosing it is a feature.
The project's thesis is that admitting limits raises trust, and no competitor does it.

### 8.3 Mining procedure

```
select public repos (GitHub Actions + pytest + active)
  -> list workflow runs with conclusion=failure
  -> keep runs where run_attempt > 1
  -> fetch logs for attempt N and attempt N+1
  -> parse BOTH with parse/pytest, the same parser production uses
  -> pair failures by test_id, requiring identical head_sha
  -> label per 8.1
  -> write JSONL with full provenance (repo, run_id, attempt, sha, url)
```

The miner deliberately reuses the production parser.
If the parser is wrong, the benchmark is wrong in the same way, which keeps the measurement honest about the tool that actually ships.

### 8.4 Dataset artifact policy

GitHub Actions log retention defaults to 90 days.
A manifest of URLs would therefore stop reproducing within three months.

The repository commits the derived `state` records, small text excerpts, together with full provenance and attribution.
Raw logs are not committed.
Sources are public repositories, and each record carries a link back to its origin.

## 9. Architecture

```
isflaky/
  core/       Failure, Answers, Verdict, Evidence. Pure domain types.
              Knows nothing about Jev, GitHub, or the CLI.

  parse/      Raw pytest log -> Failure[]
    pytest.py   test id, error message, traceback, block boundaries
    collapse.py context selection under the 32k state budget

  engine/     Decision engine. The only place Jev is named.
    protocol.py  DecisionModel: decide(state, question_set) -> Answers
    jev.py       Jev implementation
    llm.py       LLM baseline implementation
    heuristic.py regex and majority-class implementation, no network
    questions/   question sets as configuration, not code
      direct.yaml
      atomic.yaml

  gate/       Thresholds and the asymmetric-cost policy.
              Answers + thresholds -> Verdict

  mine/       GitHub Actions dataset miner. Never imported by the CLI.

  bench/      Accuracy, calibration, baselines, report generation.

  cli/        isflaky run build.log
```

### 9.1 The three load-bearing interfaces

`DecisionModel` is a protocol with one method, `decide(state, question_set) -> Answers`.
Jev, the LLM baseline, and the heuristic baseline all implement it.
This makes the baselines free, because no separate benchmark code path exists per model, and it is the structural reason this project is not a wrapper.
Swapping Jev for Laya or a local clone changes one file.

`QuestionSet` is loaded from YAML.
Comparing the direct design against the atomic design is a config swap, not a code branch.
This was the decisive architectural requirement: cheap when designed in from the start, expensive to retrofit.

`Gate` is deterministic, makes no network calls, and is testable alone with no model present.
All asymmetric-cost policy is confined here.

### 9.2 Enforced boundaries

`mine/` is never imported by `cli/`.
Dataset mining is heavy, networked, one-off work, and a user running `isflaky run` must not pay for its presence.
In practice, GitHub dependencies live behind the `[mine]` extra.

`parse/` and `gate/` never touch the network.
The hardest parts of the system, log parsing and threshold policy, are therefore fully testable without an API key, and contributors can work on them without TypeSafe credit.
This is an adoption decision, not a tidiness one.

### 9.3 Shared code path

The CLI and the benchmark run the same code path.
The benchmark swaps the source of failures and the model implementation, never the pipeline.
Benchmarks that measure a different path than production report numbers that are quietly false.

## 10. Data flows

### 10.1 Runtime

```
build.log
  -> parse/pytest      Failure[]
  -> parse/collapse    state
  -> engine.decide     Answers     one call per failure, N questions in parallel
  -> gate              Verdict + Evidence
  -> cli render
```

One call per failure, not per log.
Atomic questions must refer to a single failure or the answers blend together.
At 1,200 requests per minute, a log with 30 failures resolves in seconds.

The `state` payload is text only, per the Jev documentation:

```python
{
  "test_id":       "tests/test_api.py::test_retry",
  "error":         "ConnectionResetError: [Errno 104]",
  "traceback":     "<collapsed>",
  "log_context":   "<window around the failure>",
  "changed_files": "<from diff, when available>",
}
```

`collapse.py` enforces the 32k state budget.
Because collapse strategy affects accuracy, it is a measurable variable in later versions.

### 10.2 Benchmark

```
dataset.jsonl
  -> split: fit / holdout
  -> for each (model x question_set):
       heuristic  x  -
       jev        x  direct
       jev        x  atomic
       llm        x  direct      (small n)
  -> metrics
  -> report.md + results.json + plots (committed)
```

Thresholds are fitted on the fit split and reported on the holdout split.
Fitting and reporting on the same data is the most common way a benchmark lies, and it is prohibited here.

Every decision is cached under a hash of `(state, question_set, model)`.
Reruns are free, the $5 monthly credit stretches across many experiments, and a contributor can reproduce the report without an API key.

## 11. Question sets

### 11.1 Direct

A single `Noul`: "this failure is flaky".

### 11.2 Atomic

Roughly eight to twelve `Noul` and `Score` questions over observable signals, combined in code:

```
network_error       Noul   error mentions network, timeout, connection, or reset
timing_dependent    Noul   failure involves timing, sleep, scheduling, or ordering
assertion_failure   Noul   failure is a deterministic assertion mismatch
touches_test_code   Noul   the diff touches the failing test's module
resource_contention Noul   error mentions port, lock, file handle, or memory
external_service    Noul   failure involves an external service or API
import_or_env       Noul   failure is an import, dependency, or environment error
determinism         Score  how deterministic this failure looks, 5 levels
```

All questions run in parallel over one state read, so the tenth question costs tokens and almost no additional time.
This follows the TypeSafe documentation's explicit guidance to decompose rather than ask one complex question.

The atomic set also produces the human-readable reason required by section 7.1, and the advisory classes in section 7.4.

### 11.3 Which one ships

Both are benchmarked.
The winner becomes the default, and the comparison is published.
"One direct judgment call versus twelve atomic dimensions" is a question the whole Jev ecosystem faces and almost nobody has measured.

## 12. Benchmark design

Metrics:

- Accuracy, plus precision and recall per class.
- Expected Calibration Error, Brier score, and a reliability diagram.
- Threshold sweep under asymmetric cost, reporting the rate at which a real regression is mislabeled flaky at each operating point.
- Coverage at a target precision: how much traffic can be auto-classified, and how much must escalate.
- Cost and latency per decision.

Statistics:

- Bootstrap confidence intervals on every reported number.
- McNemar's test for Jev against each baseline.

Baselines:

- Majority class, free.
- Keyword regex over terms like timeout, connection, reset, and flake, free.
- A small LLM at n between 300 and 500, paid.

The free baselines are not optional.
If a regex reaches the same accuracy, the project's premise collapses, and that must be discovered here rather than by a reader.

Estimated cost: roughly 2,000 failures at about 4,000 tokens of state is 8M input tokens, about $0.34 on Jev.
The LLM baseline at 400 cases is roughly $0.25.
Cost is not a constraint; time is.

## 13. Error handling

Validation happens at boundaries only: the log file, the TypeSafe API, the GitHub API, and dataset files.

- An unparseable log, or one with no failures, exits cleanly with a clear message.
- One failure erroring does not abort the run; status is reported per failure.
- API 5xx and rate limits retry with backoff. 4xx and auth errors fail fast and name the missing environment variable.
- No silent fallback. A tool that guesses when its model is unavailable violates the project's entire premise.
- A `state` that exceeds 32k after collapse is truncated and marked in the output, never silently.
- Mining is long-running and must resume from a checkpoint, respect rate limits, and skip runs with expired logs while recording the reason.

## 14. Testing strategy

The entire suite runs offline with no API key.
This is an adoption requirement.

- `parse/`: golden-file tests over committed real pytest log fixtures.
- `collapse/`: property tests asserting the output is always within budget and always contains the error line.
- `gate/`: table-driven unit tests across thresholds and cost ratios.
- `engine/`: one contract suite run against all three `DecisionModel` implementations. A fake model backs the CLI tests.
- `bench/`: tested on a synthetic dataset with known answers. A perfect model must score 1.0, a random model about 0.5, and a deliberately miscalibrated fake model must be detected by the calibration metrics. If it is not, the metrics themselves are broken.
- `mine/`: recorded GitHub API response fixtures, no live calls.

Development follows TDD.

## 15. Packaging and distribution

uv, Python 3.10 or later, hatchling.

```
pip install isflaky           # parse + engine + gate + cli
pip install isflaky[mine]     # + GitHub mining
pip install isflaky[bench]    # + numpy, scipy, plots
pip install isflaky[llm]      # + baseline clients
```

MIT license.
ruff, mypy, pytest, pre-commit, GitHub Actions CI.

## 16. Discovery plan

The name carries the durable keyword; the metadata carries the trending one.
A name can hold one keyword, while description and topics hold many, so `isflaky` matches searches for flaky test tooling while the metadata matches searches for Jev.

```
repo:        isflaky
description: Flaky test triage for CI, powered by TypeSafe Jev.
             Ships with a reproducible benchmark on real CI failures.
topics:      flaky-tests, jev, typesafe-ai, ci, pytest,
             github-actions, calibration, benchmark
```

The PyPI summary must also name Jev, because PyPI search matches only name and summary.

The README opens with the headline numbers, a one-line reproduce command, and the stated limitations.
After release, submit to the roughly ten active `awesome-jev` lists, which are accepting contributions and serve as both backlinks and discovery.

The benchmark is the linkable asset.
Measured findings are what this ecosystem shares; wrappers are not.

## 17. Risks

**The dataset may not exist at sufficient scale.**
This is the project-killing risk and it is unverified.
Actions log retention is 90 days by default, `run_attempt` availability may be uneven, and public repositories that rerun failures may be rarer than assumed.

Mitigation: a half-day spike precedes all implementation, described in section 18.

**A regex baseline may match the model.**
Mitigation: the free baselines run first, before any effort goes into the CLI.
If regex wins, the project pivots or stops, cheaply.

**The ecosystem gap may close.**
Roughly 250 projects appeared in six days, so the window is short.

Mitigation: v1 is deliberately lean, and the perturbation suite is deferred to v1.1 to protect the release date.

**Vendor risk.**
Jev is early access from a single vendor.

Mitigation: the `DecisionModel` protocol keeps the project model-agnostic, and roughly twenty open Jev-compatible models already exist as alternatives.

## 18. Spike, before any implementation

Question: how many rerun-proven labeled pairs can realistically be mined?

Procedure: select five to ten public repositories with busy CI, traverse their run history, count fail-then-pass and fail-then-fail pairs at identical SHAs, and extract one full log to inspect its real shape.

The spike needs no TypeSafe API key. It uses only the GitHub API.

Decision criteria:

- 1,000 or more labeled pairs: proceed with the full plan.
- 300 to 1,000: proceed, widen the repository set, and soften the claims accordingly.
- Fewer than 300: stop and revisit the labeling strategy before writing any further code.

## 19. Scope

**v1.0, approximately one week**

- `core/`, `parse/`, `engine/`: domain types, pytest log parsing, collapse, and all three `DecisionModel` implementations
- `mine/`: dataset miner and labels
- `gate/`: thresholds and the asymmetric-cost gate
- `bench/`: accuracy, calibration, both baselines
- `cli/`: `isflaky run build.log`
- README with headline numbers and stated limits

**v1.1**

- `perturb/`: the perturbation and stability suite, measuring whether decisions hold under semantically neutral changes such as log truncation, job reordering, timestamp changes, and instruction rewording. Paired with sensitivity axes, since a constant predictor scores perfectly on invariance alone.
- A second release is a second launch moment rather than a delay.

**Later**

- GitHub Action wrapper
- Frameworks beyond pytest, most likely via JUnit XML
- Extraction of the model-agnostic benchmark harness as a standalone package

## 20. Success criteria

- The README's numbers reproduce from a clean checkout with one command.
- Jev measurably beats both free baselines, or the project honestly reports that it does not.
- Calibration is reported, and the fitted threshold holds on the holdout split.
- A reader can state, from the README alone, when the tool should not be trusted.
