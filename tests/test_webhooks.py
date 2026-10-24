import base64
import hashlib
import hmac
import json

import pytest

from app.webhooks import (
    PayloadError,
    SignatureError,
    WebhookEvent,
    parse_events,
    verify_signature,
)

SECRET = "client-secret-123"
URI = "https://svc.onrender.com/webhooks/hubspot"
NOW_MS = 1_790_000_000_000
BODY = b'[{"eventId":1,"subscriptionType":"contact.creation","objectId":5}]'


def v3_headers(body=BODY, uri=URI, method="POST", timestamp=NOW_MS, secret=SECRET):
    message = f"{method}{uri}{body.decode()}{timestamp}".encode()
    signature = base64.b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()).decode()
    return {"X-HubSpot-Signature-v3": signature, "X-HubSpot-Request-Timestamp": str(timestamp)}


def v1_headers(body=BODY, secret=SECRET):
    return {
        "X-HubSpot-Signature": hashlib.sha256(secret.encode() + body).hexdigest(),
        "X-HubSpot-Signature-Version": "v1",
    }


def verify(headers, body=BODY, uri=URI, now=NOW_MS):
    return verify_signature("POST", uri, body, headers, SECRET, now_ms=now)


# --- signature ---------------------------------------------------------------

def test_valid_v3_signature_is_accepted():
    assert verify(v3_headers()) == "v3"


def test_header_names_are_case_insensitive():
    headers = {k.lower(): v for k, v in v3_headers().items()}
    assert verify(headers) == "v3"


def test_tampered_body_is_rejected():
    with pytest.raises(SignatureError):
        verify(v3_headers(), body=BODY.replace(b"5", b"6"))


def test_wrong_secret_is_rejected():
    with pytest.raises(SignatureError):
        verify(v3_headers(secret="other"))


def test_different_uri_is_rejected():
    with pytest.raises(SignatureError):
        verify(v3_headers(uri="https://evil.example/webhooks/hubspot"))


def test_stale_timestamp_is_rejected():
    old = NOW_MS - 5 * 60 * 1000 - 1
    with pytest.raises(SignatureError, match="timestamp"):
        verify(v3_headers(timestamp=old))


def test_timestamp_within_five_minutes_is_accepted():
    assert verify(v3_headers(timestamp=NOW_MS - 4 * 60 * 1000)) == "v3"


def test_non_numeric_timestamp_is_rejected():
    headers = v3_headers() | {"X-HubSpot-Request-Timestamp": "soon"}
    with pytest.raises(SignatureError):
        verify(headers)


def test_percent_encoded_uri_characters_are_decoded_before_signing():
    signed_uri = "https://svc.onrender.com/webhooks/hubspot?x=a:b@c"
    received_uri = "https://svc.onrender.com/webhooks/hubspot?x=a%3Ab%40c"
    assert verify(v3_headers(uri=signed_uri), uri=received_uri) == "v3"


def test_valid_v1_signature_is_accepted_when_no_v3_headers():
    assert verify(v1_headers()) == "v1"


def test_invalid_v1_signature_is_rejected():
    with pytest.raises(SignatureError):
        verify(v1_headers(secret="nope"))


def test_missing_signature_headers_are_rejected():
    with pytest.raises(SignatureError, match="missing"):
        verify({})


def test_empty_client_secret_never_verifies():
    with pytest.raises(SignatureError):
        verify_signature("POST", URI, BODY, v3_headers(secret=""), "", now_ms=NOW_MS)


# --- payload parsing ---------------------------------------------------------

def test_parses_legacy_creation_events():
    payload = [
        {"eventId": 11, "subscriptionType": "company.creation", "objectId": 101, "occurredAt": 1, "attemptNumber": 0},
        {"eventId": 12, "subscriptionType": "contact.creation", "objectId": 5, "occurredAt": 2, "attemptNumber": 1},
    ]

    assert parse_events(json.dumps(payload).encode()) == [
        WebhookEvent(event_key="11", object_type="company", object_id="101", attempt=0),
        WebhookEvent(event_key="12", object_type="contact", object_id="5", attempt=1),
    ]


def test_accepts_event_type_alias():
    events = parse_events(b'[{"eventId": 1, "eventType": "contact.creation", "objectId": 5}]')
    assert events[0].object_type == "contact"


def test_parses_generic_object_creation_events():
    payload = [
        {"eventId": 21, "subscriptionType": "object.creation", "objectTypeId": "0-2", "objectId": 101},
        {"eventId": 22, "subscriptionType": "object.creation", "objectTypeId": "0-1", "objectId": 5},
        {"eventId": 23, "subscriptionType": "object.creation", "objectType": "company", "objectId": 7},
    ]

    events = parse_events(json.dumps(payload).encode())

    assert [(e.object_type, e.object_id) for e in events] == [("company", "101"), ("contact", "5"), ("company", "7")]


def test_ignores_unsupported_events():
    payload = [
        {"eventId": 1, "subscriptionType": "contact.propertyChange", "objectId": 5},
        {"eventId": 2, "subscriptionType": "object.creation", "objectTypeId": "0-3", "objectId": 9},
        {"eventId": 3, "subscriptionType": "contact.creation"},
    ]

    assert parse_events(json.dumps(payload).encode()) == []


def test_event_key_falls_back_when_event_id_missing():
    events = parse_events(b'[{"subscriptionType": "contact.creation", "objectId": 5, "occurredAt": 99}]')
    assert events[0].event_key == "contact.creation:5:99"


@pytest.mark.parametrize("body", [b"not json", b'{"eventId": 1}', b"[1, 2]", b""])
def test_malformed_payloads_raise(body):
    with pytest.raises(PayloadError):
        parse_events(body)
