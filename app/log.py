"""Structured JSON logging with redaction of secrets and personal data."""

import json
import logging
import re
import sys
from datetime import datetime, timezone

_PATTERNS = [
    (re.compile(r"(?i)(x-api-key|authorization|bearer|token|secret)([\"']?\s*[:=]?\s*)[A-Za-z0-9._\-]{12,}"), r"\1\2[REDACTED]"),
    (re.compile(r"\bpat-[a-z0-9]+-[A-Za-z0-9\-]+"), "[REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
]
_PHONE_CANDIDATE = re.compile(r"(?<![\w.:])[+(]?\d[\d\s().-]{6,}\d")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _mask_phone(match: re.Match) -> str:
    """Mask phone-like digit runs; keep record ids, dates and decimals readable."""
    text = match.group(0)
    digits = sum(c.isdigit() for c in text)
    looks_formatted = text[0] in "+(" or any(c in text for c in " -()")
    if 7 <= digits <= 15 and looks_formatted and not _ISO_DATE.search(text):
        return "[PHONE]"
    return text


def redact(value):
    """Mask tokens, emails and phone numbers in strings; recurse into containers."""
    if isinstance(value, str):
        for pattern, replacement in _PATTERNS:
            value = pattern.sub(replacement, value)
        return _PHONE_CANDIDATE.sub(_mask_phone, value)
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        payload.update(redact(getattr(record, "fields", None) or {}))
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # httpx logs full request URLs at INFO; keep them out of the default stream.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    """Log a named event with structured fields, e.g. log_event(log, "webhook.accepted", count=2)."""
    logger.log(level, event, extra={"fields": fields})
