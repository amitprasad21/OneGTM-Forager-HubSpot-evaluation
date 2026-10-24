import json

import httpx
import pytest
import respx

from app.clients.forager import ForagerAuthError, ForagerClient, ForagerError
from app.credits import CreditBudgetExceeded, InMemoryCreditLedger

BASE = "https://api-v2.forager.ai"
ACCOUNT = "1234"
DS = f"{BASE}/api/{ACCOUNT}/datastorage"
WORK_EMAILS = f"{BASE}/api/v2/{ACCOUNT}/datastorage/person_contacts_lookup/work_emails/"


async def no_sleep(_seconds):
    return None


@pytest.fixture
def ledger():
    return InMemoryCreditLedger(budget=100)


@pytest.fixture
async def forager(ledger):
    client = ForagerClient(api_key="test-key", account_id=ACCOUNT, ledger=ledger, sleep=no_sleep)
    yield client
    await client.aclose()


def body(route):
    return json.loads(route.calls.last.request.content)


# --- auth & errors -----------------------------------------------------------

@respx.mock
async def test_sends_api_key_header_and_account_path(forager):
    route = respx.post(f"{DS}/organization_search/").mock(
        return_value=httpx.Response(200, json={"search_results": [], "total_search_results": 0})
    )

    await forager.search_organizations(domains=["openai.com"])

    assert route.calls.last.request.headers["X-API-KEY"] == "test-key"
    assert body(route) == {"domains": ["openai.com"], "page": 1}


@respx.mock
@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failures_raise_auth_error(forager, status):
    respx.post(f"{DS}/organization_search/").mock(return_value=httpx.Response(status))

    with pytest.raises(ForagerAuthError):
        await forager.search_organizations(domains=["openai.com"])


@respx.mock
async def test_server_error_after_retries_raises(forager):
    route = respx.post(f"{DS}/person_detail_lookup/").mock(return_value=httpx.Response(500))

    with pytest.raises(ForagerError):
        await forager.get_person_detail(linkedin_slug="jane")

    assert route.call_count == 3


@respx.mock
async def test_error_message_does_not_include_api_key(forager):
    respx.post(f"{DS}/person_detail_lookup/").mock(return_value=httpx.Response(400, json={"detail": "bad"}))

    with pytest.raises(ForagerError) as excinfo:
        await forager.get_person_detail(person_id=1)

    assert "test-key" not in str(excinfo.value)
    assert "400" in str(excinfo.value)


# --- organizations -----------------------------------------------------------

@respx.mock
async def test_search_organizations_returns_payload_and_records_credit(forager, ledger):
    payload = {"search_results": [{"id": 7, "name": "OpenAI"}], "total_search_results": 1}
    respx.post(f"{DS}/organization_search/").mock(return_value=httpx.Response(200, json=payload))

    result = await forager.search_organizations(domains=["openai.com"])

    assert result == payload
    assert ledger.spent == 1


@respx.mock
async def test_autocomplete_organizations_is_free_get_with_query(forager, ledger):
    route = respx.get(f"{DS}/autocomplete/organizations/").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "7", "text": "OpenAI - openai.com"}]})
    )

    results = await forager.autocomplete_organizations("OpenAI")

    assert results == [{"id": "7", "text": "OpenAI - openai.com"}]
    assert route.calls.last.request.url.params["q"] == "OpenAI"
    assert ledger.spent == 0


# --- people ------------------------------------------------------------------

@respx.mock
async def test_person_role_search_drops_none_filters(forager, ledger):
    route = respx.post(f"{DS}/person_role_search/").mock(
        return_value=httpx.Response(200, json={"search_results": [], "total_search_results": 0})
    )

    await forager.search_person_roles(
        organization_domains=["openai.com"], role_title='"VP"', role_is_current=True, person_name=None
    )

    assert body(route) == {
        "organization_domains": ["openai.com"],
        "role_title": '"VP"',
        "role_is_current": True,
        "page": 1,
    }
    assert ledger.spent == 1


@respx.mock
async def test_person_detail_by_slug(forager, ledger):
    route = respx.post(f"{DS}/person_detail_lookup/").mock(
        return_value=httpx.Response(200, json={"id": 1, "full_name": "Jane Doe"})
    )

    person = await forager.get_person_detail(linkedin_slug="jane-doe")

    assert person["id"] == 1
    assert body(route) == {"linkedin_public_identifier": "jane-doe"}
    assert ledger.spent == 1


@respx.mock
@pytest.mark.parametrize(
    "response",
    [httpx.Response(404), httpx.Response(200, content=b""), httpx.Response(200, json={})],
)
async def test_person_detail_not_found_returns_none(forager, response):
    respx.post(f"{DS}/person_detail_lookup/").mock(return_value=response)

    assert await forager.get_person_detail(person_id=99) is None


async def test_person_detail_requires_an_identifier(forager):
    with pytest.raises(ValueError):
        await forager.get_person_detail()


@respx.mock
async def test_reverse_lookup_by_email(forager, ledger):
    route = respx.post(f"{DS}/person_detail_reverse_lookup/by_email/").mock(
        return_value=httpx.Response(200, json={"id": 3, "full_name": "X"})
    )

    person = await forager.reverse_lookup_email("x@openai.com")

    assert person["id"] == 3
    assert body(route) == {"email": "x@openai.com"}
    assert ledger.spent == 5


# --- contact lookups ---------------------------------------------------------

@respx.mock
async def test_phone_lookup_returns_first_number_and_charges_15(forager, ledger):
    route = respx.post(f"{DS}/person_contacts_lookup/phone_numbers/").mock(
        return_value=httpx.Response(200, json=[{"phone_number": "+14155552671"}, {"phone_number": "+1999"}])
    )

    assert await forager.find_phone(person_id=1) == "+14155552671"
    assert body(route) == {"person_id": 1}
    assert ledger.spent == 15


@respx.mock
@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, json=[]), httpx.Response(200, content=b""), httpx.Response(404)],
)
async def test_phone_not_found_returns_none_and_charges_nothing(forager, ledger, response):
    respx.post(f"{DS}/person_contacts_lookup/phone_numbers/").mock(return_value=response)

    assert await forager.find_phone(person_id=1) is None
    assert ledger.spent == 0


@respx.mock
async def test_personal_email_prefers_valid(forager, ledger):
    respx.post(f"{DS}/person_contacts_lookup/personal_emails/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"email": "risky@gmail.com", "email_type": "personal", "validation_status": "risky"},
                {"email": "good@gmail.com", "email_type": "personal", "validation_status": "valid"},
            ],
        )
    )

    assert await forager.find_personal_email(person_id=1) == "good@gmail.com"
    assert ledger.spent == 5


@respx.mock
async def test_personal_email_ignores_invalid_only_results(forager):
    respx.post(f"{DS}/person_contacts_lookup/personal_emails/").mock(
        return_value=httpx.Response(
            200, json=[{"email": "x@gmail.com", "email_type": "p", "validation_status": "invalid"}]
        )
    )

    assert await forager.find_personal_email(person_id=1) is None


@respx.mock
async def test_work_email_polls_until_completed(forager, ledger):
    start = respx.post(WORK_EMAILS).mock(
        return_value=httpx.Response(202, json={"job_id": "j1", "status": "queued", "status_check_url": "x"})
    )
    poll = respx.get(f"{WORK_EMAILS}j1/").mock(
        side_effect=[
            httpx.Response(200, json={"status": "running", "emails": []}, headers={"Retry-After": "1"}),
            httpx.Response(
                200, json={"status": "completed", "result": "found", "emails": [["jane@openai.com", "valid"]]}
            ),
        ]
    )

    email = await forager.find_work_email(linkedin_slug="jane-doe")

    assert email == "jane@openai.com"
    assert body(start) == {"linkedin_public_identifier": "jane-doe"}
    assert poll.call_count == 2
    assert ledger.spent == 5


@respx.mock
@pytest.mark.parametrize(
    "emails, expected",
    [
        (["plain@openai.com"], "plain@openai.com"),
        ([{"email": "obj@openai.com", "verdict": "valid"}], "obj@openai.com"),
        ([["risky@openai.com", "risky"], ["ok@openai.com", "valid"]], "ok@openai.com"),
    ],
)
async def test_work_email_accepts_possible_item_shapes(forager, emails, expected):
    respx.post(WORK_EMAILS).mock(return_value=httpx.Response(202, json={"job_id": "j2", "status": "queued"}))
    respx.get(f"{WORK_EMAILS}j2/").mock(
        return_value=httpx.Response(200, json={"status": "completed", "result": "found", "emails": emails})
    )

    found = await forager.find_work_email(first_name="Jane", last_name="Doe", domain="openai.com")

    assert found == expected


@respx.mock
@pytest.mark.parametrize(
    "final",
    [
        {"status": "completed", "result": "not_found", "emails": []},
        {"status": "failed", "error_code": "person_not_found", "emails": []},
    ],
)
async def test_work_email_not_found_or_failed_returns_none_without_charge(forager, ledger, final):
    respx.post(WORK_EMAILS).mock(return_value=httpx.Response(202, json={"job_id": "j3", "status": "queued"}))
    respx.get(f"{WORK_EMAILS}j3/").mock(return_value=httpx.Response(200, json=final))

    assert await forager.find_work_email(linkedin_slug="x") is None
    assert ledger.spent == 0


@respx.mock
async def test_work_email_poll_gives_up_after_max_wait(ledger):
    client = ForagerClient(
        api_key="k",
        account_id=ACCOUNT,
        ledger=ledger,
        sleep=no_sleep,
        work_email_max_wait=6,
        work_email_poll_interval=2,
    )
    respx.post(WORK_EMAILS).mock(return_value=httpx.Response(202, json={"job_id": "j4", "status": "queued"}))
    poll = respx.get(f"{WORK_EMAILS}j4/").mock(
        return_value=httpx.Response(200, json={"status": "running", "emails": []})
    )

    assert await client.find_work_email(linkedin_slug="x") is None
    assert poll.call_count == 4  # t=0, 2, 4, 6
    await client.aclose()


async def test_work_email_requires_slug_or_name_and_domain(forager):
    with pytest.raises(ValueError):
        await forager.find_work_email(first_name="Jane")


# --- credit budget -----------------------------------------------------------

@respx.mock
async def test_budget_guard_blocks_call_before_spending():
    ledger = InMemoryCreditLedger(budget=10)
    client = ForagerClient(api_key="k", account_id=ACCOUNT, ledger=ledger, sleep=no_sleep)
    route = respx.post(f"{DS}/person_contacts_lookup/phone_numbers/").mock(
        return_value=httpx.Response(200, json=[])
    )

    with pytest.raises(CreditBudgetExceeded):
        await client.find_phone(person_id=1)

    assert route.call_count == 0
    await client.aclose()


@respx.mock
async def test_get_credit_balance_for_configured_account(forager, ledger):
    respx.get(f"{BASE}/api/users/current/").mock(
        return_value=httpx.Response(
            200,
            json={"accounts": [{"id": 1, "subscription": {"credits_balance": "9.00"}},
                               {"id": 1234, "subscription": {"credits_balance": "50.00"}}]},
        )
    )

    assert await forager.get_credit_balance() == 50
    assert ledger.spent == 0


@respx.mock
async def test_get_credit_balance_unknown_account_returns_none(forager):
    respx.get(f"{BASE}/api/users/current/").mock(return_value=httpx.Response(200, json={"accounts": []}))

    assert await forager.get_credit_balance() is None
