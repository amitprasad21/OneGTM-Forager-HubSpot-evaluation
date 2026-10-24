import json
import logging

from app.log import JsonFormatter, redact


def test_redact_masks_emails_phones_and_tokens():
    text = (
        "user jane.doe@openai.com phone +1 (415) 555-2671 "
        "token pat-na2-abcdef12-3456 header X-API-KEY: abcdef0123456789abcdef"
    )

    redacted = redact(text)

    assert "jane.doe@openai.com" not in redacted
    assert "555-2671" not in redacted
    assert "pat-na2-abcdef12-3456" not in redacted
    assert "abcdef0123456789abcdef" not in redacted
    assert "[EMAIL]" in redacted and "[PHONE]" in redacted


def test_redact_keeps_ordinary_ids_and_text():
    assert redact("company 123456 enriched in 2.5s") == "company 123456 enriched in 2.5s"


def test_redact_keeps_long_numeric_record_ids():
    # HubSpot object ids are plain digit strings and must stay readable in logs.
    assert redact("contact 999999999999 done") == "contact 999999999999 done"
    assert redact({"object_id": "123456789012"}) == {"object_id": "123456789012"}


def test_redact_masks_unformatted_international_numbers():
    assert redact("phone +14155552671") == "phone [PHONE]"


def test_redact_masks_bracketed_area_code_completely():
    assert redact("call (415) 555-2671") == "call [PHONE]"


def test_redact_keeps_dates_timestamps_and_decimals():
    text = "at 2026-10-24T05:47:22.141629+00:00 took 22.141629 s, founded 2015-12-11"
    assert redact(text) == text


def test_json_formatter_redacts_message_and_extra_fields():
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "contact %s", ("a@b.co",), None)
    record.fields = {"email": "a@b.co", "object_id": 42}

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["message"] == "contact [EMAIL]"
    assert payload["email"] == "[EMAIL]"
    assert payload["object_id"] == 42
