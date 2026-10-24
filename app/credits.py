"""Forager credit accounting and budget guard.

Costs come from https://docs.forager.ai/api-overview/credit-pricing.md.
"""

from typing import Protocol

COST_ORGANIZATION_SEARCH = 1
COST_PERSON_ROLE_SEARCH = 1
COST_PERSON_DETAIL = 1
COST_REVERSE_EMAIL = 5
COST_WORK_EMAIL = 5
COST_PERSONAL_EMAIL = 5
COST_PHONE = 15


class CreditBudgetExceeded(RuntimeError):
    """Raised before a call that could take spend past the configured budget."""


class CreditLedger(Protocol):
    @property
    def spent(self) -> int: ...

    def ensure_available(self, cost: int) -> None: ...

    def record(self, cost: int, operation: str) -> None: ...


class InMemoryCreditLedger:
    def __init__(self, budget: int):
        self.budget = budget
        self._spent = 0

    @property
    def spent(self) -> int:
        return self._spent

    @property
    def remaining(self) -> int:
        return self.budget - self._spent

    def ensure_available(self, cost: int) -> None:
        if cost > self.remaining:
            raise CreditBudgetExceeded(
                f"Forager credit budget exhausted: need {cost}, {self.remaining} of {self.budget} left"
            )

    def record(self, cost: int, operation: str) -> None:
        if cost > 0:
            self._spent += cost
