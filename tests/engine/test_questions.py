import pytest

from isflaky.engine.questions import Kind, load_question_set

DIRECT_YAML = """
name: direct
questions:
  - name: flaky
    kind: noul
    prompt: This failure is flaky.
"""

ATOMIC_YAML = """
name: atomic
questions:
  - name: network_error
    kind: noul
    prompt: The error mentions a network problem.
  - name: determinism
    kind: score
    prompt: How deterministic is this failure?
    levels:
      - fully nondeterministic
      - unclear
      - fully deterministic
"""


def write(tmp_path, body: str):
    path = tmp_path / "set.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_name_and_questions(tmp_path):
    question_set = load_question_set(write(tmp_path, DIRECT_YAML))
    assert question_set.name == "direct"
    assert [q.name for q in question_set.questions] == ["flaky"]
    assert question_set.questions[0].kind is Kind.NOUL
    assert question_set.questions[0].prompt == "This failure is flaky."


def test_preserves_question_order(tmp_path):
    question_set = load_question_set(write(tmp_path, ATOMIC_YAML))
    assert [q.name for q in question_set.questions] == ["network_error", "determinism"]


def test_score_questions_carry_their_levels(tmp_path):
    question_set = load_question_set(write(tmp_path, ATOMIC_YAML))
    determinism = question_set.questions[1]
    assert determinism.kind is Kind.SCORE
    assert determinism.levels == ("fully nondeterministic", "unclear", "fully deterministic")


def test_unknown_kind_is_rejected(tmp_path):
    body = "name: bad\nquestions:\n  - name: x\n    kind: guess\n    prompt: p\n"
    with pytest.raises(ValueError, match="guess"):
        load_question_set(write(tmp_path, body))


def test_score_question_without_levels_is_rejected(tmp_path):
    body = "name: bad\nquestions:\n  - name: x\n    kind: score\n    prompt: p\n"
    with pytest.raises(ValueError, match="levels"):
        load_question_set(write(tmp_path, body))


def test_empty_question_list_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="at least one question"):
        load_question_set(write(tmp_path, "name: empty\nquestions: []\n"))


def test_duplicate_question_names_are_rejected(tmp_path):
    body = (
        "name: dup\nquestions:\n"
        "  - name: x\n    kind: noul\n    prompt: a\n"
        "  - name: x\n    kind: noul\n    prompt: b\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_question_set(write(tmp_path, body))


@pytest.mark.parametrize("name", ["direct", "atomic"])
def test_packaged_sets_load_by_bare_name(name):
    """A bare name resolves against the packaged question sets."""
    question_set = load_question_set(name)
    assert question_set.name == name
    assert question_set.questions


def test_packaged_atomic_set_matches_the_spec():
    question_set = load_question_set("atomic")
    names = {q.name for q in question_set.questions}
    assert names == {
        "network_error",
        "timing_dependent",
        "assertion_failure",
        "touches_test_code",
        "resource_contention",
        "external_service",
        "import_or_env",
        "determinism",
    }
