"""Scientist decisions: accept or exclude, saved and reapplied.

Exclusions never delete anything. They are stored with a reason and a time,
can be undone, and are applied to every future answer:
- value:    this value from this element (e.g. attack rate 6.2 in p3-table1)
- element:  everything cited from this table, figure or paragraph
- document: everything from this document
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from .reporter import Report
from .schema import Extraction

Scope = Literal["value", "element", "document"]
Action = Literal["accepted", "excluded"]


class Decision(BaseModel):
    scope: Scope
    action: Action
    document: str
    element_id: Optional[str] = None
    measure: Optional[str] = None
    value: Optional[float] = None
    reason: str = ""
    time: str = ""

    def matches(self, x: Extraction) -> bool:
        if x.source.document != self.document:
            return False
        if self.scope == "document":
            return True
        if x.source.element_id != self.element_id:
            return False
        if self.scope == "element":
            return True
        return (x.draft.measure_as_reported.lower() == (self.measure or "").lower()
                and x.draft.value == self.value)

    def describe(self) -> str:
        if self.scope == "document":
            target = self.document
        elif self.scope == "element":
            target = f"{self.document}, {self.element_id}"
        else:
            target = f"{self.measure} = {self.value:g} ({self.document}, {self.element_id})"
        return f"{self.action.capitalize()}: {target}" + (f". Reason: {self.reason}" if self.reason else "")


def decision_for(x: Extraction, scope: Scope, action: Action, reason: str = "") -> Decision:
    return Decision(
        scope=scope, action=action, document=x.source.document,
        element_id=None if scope == "document" else x.source.element_id,
        measure=x.draft.measure_as_reported if scope == "value" else None,
        value=x.draft.value if scope == "value" else None,
        reason=reason.strip(),
        time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


class DecisionStore:
    def __init__(self, path: str | Path = "outputs/decisions.json"):
        self.path = Path(path)
        self.decisions: list[Decision] = []
        if self.path.exists():
            self.decisions = [Decision.model_validate(d) for d in json.loads(self.path.read_text())]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([d.model_dump() for d in self.decisions], indent=2))

    def add(self, decision: Decision) -> None:
        # a newer decision on the same target replaces the older one
        self.decisions = [d for d in self.decisions
                          if (d.scope, d.document, d.element_id, d.measure, d.value)
                          != (decision.scope, decision.document, decision.element_id,
                              decision.measure, decision.value)]
        self.decisions.append(decision)
        self.save()

    def undo(self, index: int) -> None:
        del self.decisions[index]
        self.save()

    def apply(self, report: Report) -> Report:
        """Set each answer's status. Exclusions win over acceptances; broader scopes apply too."""
        for x in report.answers:
            hits = [d for d in self.decisions if d.matches(x)]
            if any(d.action == "excluded" for d in hits):
                x.status = "excluded"
            elif any(d.action == "accepted" for d in hits):
                x.status = "accepted"
            else:
                x.status = "pending"
        return report
