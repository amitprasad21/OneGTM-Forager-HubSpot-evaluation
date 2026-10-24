import httpx
import pytest
import respx

from scripts import admin

URL = "https://svc.onrender.com"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SERVICE_URL", URL + "/")
    monkeypatch.setattr(admin, "admin_key", lambda: "secret-admin-key")
    monkeypatch.setattr(admin, "load_dotenv", lambda: None)  # ignore the developer's real .env


@respx.mock
def test_discover_sends_filter_and_prints_candidates(capsys):
    route = respx.post(f"{URL}/admin/discover").mock(
        return_value=httpx.Response(
            200,
            json={
                "filter": "include: Engineer; exclude: none",
                "candidates": [{"name": "A B", "job_title": "Software Engineer", "linkedin_url": "https://x"}],
            },
        )
    )

    admin.main(["discover", "openai.com", "--include", "Engineer"])

    request = route.calls.last.request
    assert request.headers["X-Admin-Key"] == "secret-admin-key"
    assert b'"include_titles":["Engineer"]' in request.content.replace(b" ", b"")
    output = capsys.readouterr().out
    assert "Software Engineer" in output
    assert "secret-admin-key" not in output


@respx.mock
def test_enrich_company_passes_force(capsys):
    route = respx.post(f"{URL}/admin/enrich/company/101").mock(return_value=httpx.Response(200, json={"ok": True}))

    admin.main(["enrich-company", "101", "--force"])

    assert route.calls.last.request.url.params["force"] == "true"


def test_missing_service_url_exits_with_message(monkeypatch):
    monkeypatch.delenv("SERVICE_URL")

    with pytest.raises(SystemExit, match="SERVICE_URL"):
        admin.main(["health"])
