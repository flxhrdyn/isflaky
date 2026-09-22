from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

import yaml

_PACKAGED = Path(__file__).parent / "questions"


class Kind(str, Enum):
    NOUL = "noul"
    SCORE = "score"


@dataclass(frozen=True)
class Question:
    name: str
    kind: Kind
    prompt: str
    levels: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuestionSet:
    name: str
    questions: tuple[Question, ...]


def load_question_set(name_or_path: str | Path) -> QuestionSet:
    path = _resolve(name_or_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = raw.get("questions") or []
    if not entries:
        _reject(path, "needs at least one question")

    questions = tuple(_parse_question(entry, path) for entry in entries)
    names = [question.name for question in questions]
    if len(set(names)) != len(names):
        _reject(path, "has duplicate question names")

    return QuestionSet(name=raw["name"], questions=questions)


def _resolve(name_or_path: str | Path) -> Path:
    path = Path(name_or_path)
    if path.suffix or path.exists():
        return path
    return _PACKAGED / f"{name_or_path}.yaml"


def _parse_question(entry: Mapping[str, Any], path: Path) -> Question:
    raw_kind = entry["kind"]
    try:
        kind = Kind(raw_kind)
    except ValueError:
        _reject(path, f"has unknown question kind {raw_kind!r}")

    levels = tuple(str(level) for level in entry.get("levels") or ())
    if kind is Kind.SCORE and not levels:
        _reject(path, f"question {entry['name']!r} is a score but has no levels")

    return Question(
        name=str(entry["name"]),
        kind=kind,
        prompt=str(entry["prompt"]),
        levels=levels,
    )


def _reject(path: Path, problem: str) -> NoReturn:
    raise ValueError(f"question set {path.name} {problem}")
