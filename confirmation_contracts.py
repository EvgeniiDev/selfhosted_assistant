from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfirmationContract:
    action: str
    pending_kind: str


EVENT_CONFIRMATION = ConfirmationContract(
    action="confirm",
    pending_kind="event",
)

TASK_CONFIRMATION = ConfirmationContract(
    action="confirm_task",
    pending_kind="task",
)