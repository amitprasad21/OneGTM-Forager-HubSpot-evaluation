import pytest

from app.credits import CreditBudgetExceeded, InMemoryCreditLedger


def test_records_spend_and_reports_remaining():
    ledger = InMemoryCreditLedger(budget=20)

    ledger.record(5, "work_email")
    ledger.record(1, "person_detail")

    assert ledger.spent == 6
    assert ledger.remaining == 14


def test_ensure_available_raises_when_cost_exceeds_remaining():
    ledger = InMemoryCreditLedger(budget=10)
    ledger.record(1, "search")

    ledger.ensure_available(9)
    with pytest.raises(CreditBudgetExceeded):
        ledger.ensure_available(15)


def test_zero_cost_records_are_ignored():
    ledger = InMemoryCreditLedger(budget=1)
    ledger.record(0, "poll")
    assert ledger.spent == 0
