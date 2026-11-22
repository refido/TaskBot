from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class TransactionOutcome:
    """Observed sale result, independent of CAPTCHA completion.

    These are observation states, not new persisted report statuses. Business
    rejections retain the reporter's existing skip categories.
    """

    status: Literal["completed", "blocked", "unknown"]
    reason: str = ""
    evidence: str = ""

    @property
    def success_confirmed(self) -> bool:
        return self.status == "completed" and bool(self.evidence.strip())


class TransactionConfirmationError(RuntimeError):
    """A submitted sale has no confirmed outcome; automatic replay is unsafe."""
