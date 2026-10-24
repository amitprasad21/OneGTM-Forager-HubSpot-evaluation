"""HubSpot webhook signature verification and payload parsing (docs/api-contracts.md §2.2–2.3)."""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

MAX_TIMESTAMP_AGE_MS = 5 * 60 * 1000

# Percent-encodings HubSpot decodes before signing the URI (request validation guide).
_URI_DECODINGS = {
    "%3A": ":", "%2F": "/", "%3F": "?", "%40": "@", "%21": "!", "%24": "$",
    "%27": "'", "%28": "(", "%29": ")", "%2A": "*", "%2C": ",", "%3B": ";",
}

_LEGACY_TYPES = {"contact.creation": "contact", "company.creation": "company"}
_OBJECT_TYPE_IDS = {"0-1": "contact", "0-2": "company"}


class SignatureError(Exception):
    pass


class PayloadError(Exception):
    pass


@dataclass(frozen=True)
class WebhookEvent:
    event_key: str
    object_type: str  # "company" | "contact"
    object_id: str
    attempt: int = 0


def verify_signature(
    method: str, uri: str, body: bytes, headers, client_secret: str, *, now_ms: int
) -> str:
    """Verify a HubSpot request; returns the signature version used ("v3" or "v1")."""
    if not client_secret:
        raise SignatureError("client secret not configured")
    lowered = {key.lower(): value for key, value in dict(headers).items()}

    signature_v3 = lowered.get("x-hubspot-signature-v3")
    if signature_v3:
        timestamp = lowered.get("x-hubspot-request-timestamp", "")
        if not timestamp.isdigit():
            raise SignatureError("invalid timestamp header")
        if now_ms - int(timestamp) > MAX_TIMESTAMP_AGE_MS:
            raise SignatureError("timestamp older than 5 minutes")
        message = f"{method.upper()}{_decode_uri(uri)}{body.decode('utf-8')}{timestamp}".encode()
        expected = base64.b64encode(
            hmac.new(client_secret.encode(), message, hashlib.sha256).digest()
        ).decode()
        if not hmac.compare_digest(expected, signature_v3):
            raise SignatureError("v3 signature mismatch")
        return "v3"

    signature_v1 = lowered.get("x-hubspot-signature")
    if signature_v1:
        expected = hashlib.sha256(client_secret.encode() + body).hexdigest()
        if not hmac.compare_digest(expected, signature_v1):
            raise SignatureError("v1 signature mismatch")
        return "v1"

    raise SignatureError("missing signature headers")


def parse_events(body: bytes) -> list[WebhookEvent]:
    """Parse a webhook body into supported creation events; others are ignored."""
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise PayloadError("body is not valid JSON") from error
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise PayloadError("body must be a JSON array of event objects")

    events = []
    for item in payload:
        object_type = _object_type(item)
        object_id = item.get("objectId")
        if object_type is None or object_id in (None, ""):
            continue
        subscription = item.get("subscriptionType") or item.get("eventType")
        event_id = item.get("eventId")
        key = str(event_id) if event_id not in (None, "") else f"{subscription}:{object_id}:{item.get('occurredAt')}"
        events.append(
            WebhookEvent(
                event_key=key,
                object_type=object_type,
                object_id=str(object_id),
                attempt=int(item.get("attemptNumber") or 0),
            )
        )
    return events


def _object_type(item: dict) -> str | None:
    subscription = item.get("subscriptionType") or item.get("eventType")
    if subscription in _LEGACY_TYPES:
        return _LEGACY_TYPES[subscription]
    if subscription == "object.creation":
        object_type = _OBJECT_TYPE_IDS.get(str(item.get("objectTypeId")))
        if object_type is None and item.get("objectType") in ("contact", "company"):
            object_type = item["objectType"]
        return object_type
    return None


def _decode_uri(uri: str) -> str:
    for encoded, decoded in _URI_DECODINGS.items():
        uri = uri.replace(encoded, decoded).replace(encoded.lower(), decoded)
    return uri
