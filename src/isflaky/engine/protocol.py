from collections.abc import Mapping
from typing import Protocol

from isflaky.core.models import Answers
from isflaky.engine.questions import QuestionSet


class DecisionModel(Protocol):
    """The one seam between this project and any model behind it.

    Jev, the Groq baseline, and the regex heuristic all implement this, which is
    why the baselines cost no extra benchmark code and why swapping Jev out
    touches a single file.
    """

    def decide(self, state: Mapping[str, str], questions: QuestionSet) -> Answers: ...
