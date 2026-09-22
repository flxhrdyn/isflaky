# isflaky

Triage a failing pytest run in CI: is this test flaky, or is it a real regression?

**Status: work in progress.** The dataset and the decision engine exist and are
tested; the CLI does not exist yet, and no accuracy numbers are published. This
README will carry them, with confidence intervals and sample size, once the
benchmark runs on a dataset I trust.

## Why another one

Several tools already classify CI failures. None of them publish evidence that
their classification is correct, so there is no way to tell a good one from a
plausible-sounding one.

This project's deliverable is that evidence. The triage feature is ordinary; the
benchmark is the point.

## Ground truth without hand labelling

Labels come only from GitHub Actions rerun evidence at an identical commit:

```
same head_sha, consecutive run attempts:

  attempt N FAIL -> attempt N+1 PASS   = flaky
  attempt N FAIL -> attempt N+1 FAIL   = real regression
  attempt N FAIL -> no rerun exists    = unlabeled, discarded
```

Nobody's judgement enters the labels. A failure nobody reran is dropped rather
than assumed real: treating unlabeled failures as regressions would turn that
class into a dumping ground and inflate every number computed from it.

## Known limitations

These are stated here, next to the claims, rather than in a footnote.

- **Selection bias.** The dataset covers only failures somebody chose to rerun,
  which skews toward failures that looked rerunnable to a human.
- **Log retention.** GitHub deletes per-attempt log archives far sooner than the
  runs disappear from the API. Repositories with hundreds of eligible reruns
  still yield nothing because their logs are already gone, which binds the
  dataset's size far more than mining speed does.
- **Repository concentration.** For the same reason, the current dataset is
  dominated by a single repository, so no claim here generalises to Python CI at
  large.
- **Sample size.** The dataset is well below the 1,000 pairs the design assumed.
  Every published number will carry a bootstrap confidence interval and its n.

## How it decides

```
pytest log -> parse -> collapse to a state -> model -> gate -> verdict
```

The model is one interface with a single method, so [TypeSafe Jev][jev], a small
LLM baseline on Groq, and a regex heuristic all run through the same path and
the same tests. The baselines cost no extra benchmark code, and swapping the
model touches one file.

The gate is separate from the model and holds every cost decision. Calling a
real regression flaky is the expensive mistake - it tells someone to rerun a
genuine break - so the decision threshold is fitted under an explicit cost
ratio, and a verdict below the confidence threshold escalates instead of
answering. An escalated verdict never reports that a rerun is safe.

Questions live in YAML, so comparing one direct question against eight atomic
ones is a config change rather than a code branch.

[jev]: https://typesafe.ai

## Running it

```bash
uv sync --all-extras

# Mine labeled failures from public repositories (needs GITHUB_TOKEN).
uv run isflaky-mine scrapy/scrapy pytest-dev/pytest --out data/dataset.jsonl

# Benchmark every model whose API key is present.
uv run python -m isflaky.bench --dataset data/dataset.jsonl

# Re-analyse saved results without spending another API call.
uv run python -m isflaky.bench --replay data/results.jsonl
```

Copy `.env.example` to `.env` for the keys. The test suite runs offline and
needs none of them:

```bash
uv run pytest
```

## License

MIT.
