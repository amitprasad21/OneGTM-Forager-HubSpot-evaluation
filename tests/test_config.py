import pytest

from app.config import ConfigError, Settings

REQUIRED = {
    "forager_api_key": "fk-secret-value-123",
    "forager_account_id": "1234",
    "hubspot_access_token": "pat-na2-secret-token",
    "hubspot_client_secret": "client-secret-xyz",
    "admin_api_key": "admin-secret",
}


def make_settings(**overrides):
    return Settings(_env_file=None, **{**REQUIRED, **overrides})


def test_validate_passes_when_all_required_values_present():
    make_settings().validate_required()


def test_validate_names_missing_variables_without_values():
    settings = make_settings(hubspot_access_token="", hubspot_client_secret="")

    with pytest.raises(ConfigError) as excinfo:
        settings.validate_required()

    message = str(excinfo.value)
    assert "HUBSPOT_ACCESS_TOKEN" in message
    assert "HUBSPOT_CLIENT_SECRET" in message
    assert "FORAGER_API_KEY" not in message


def test_account_id_must_be_an_integer():
    with pytest.raises(ConfigError, match="FORAGER_ACCOUNT_ID"):
        make_settings(forager_account_id="abc").validate_required()


def test_repr_and_dump_do_not_leak_secrets():
    settings = make_settings()
    rendered = repr(settings) + str(settings.model_dump())

    for secret in ("fk-secret-value-123", "pat-na2-secret-token", "client-secret-xyz", "admin-secret"):
        assert secret not in rendered


def test_defaults_for_optional_settings():
    settings = make_settings()

    assert settings.forager_credit_budget == 500  # safety cap; live balance caps it further at startup
    assert settings.max_phone_lookups_per_job is None  # no per-job limit unless configured
    assert settings.enable_personal_email_lookup is True
    assert settings.discovery_max_contacts == 5
    assert settings.enrich_extra_fields is False
    assert settings.enable_phone_lookup is True
    assert settings.public_base_url == ""


def test_title_lists_are_parsed_from_comma_separated_env(monkeypatch):
    monkeypatch.setenv("DISCOVERY_TITLES", "VP, Head of ,Director")
    monkeypatch.setenv("DISCOVERY_EXCLUDE_TITLES", "Intern")

    settings = Settings(_env_file=None, **REQUIRED)

    assert settings.discovery_titles == ["VP", "Head of", "Director"]
    assert settings.discovery_exclude_titles == ["Intern"]


def test_webhook_base_url_prefers_public_base_url_then_render():
    assert make_settings(public_base_url="https://a.example/").webhook_base_url == "https://a.example"
    assert make_settings(render_external_url="https://svc.onrender.com").webhook_base_url == "https://svc.onrender.com"


def test_phone_limit_can_be_configured_from_env(monkeypatch):
    monkeypatch.setenv("MAX_PHONE_LOOKUPS_PER_JOB", "2")

    assert Settings(_env_file=None, **REQUIRED).max_phone_lookups_per_job == 2
