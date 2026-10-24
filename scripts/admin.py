"""Call the service's admin endpoints without exposing the admin key.

Reads ADMIN_API_KEY from .env and the target from SERVICE_URL, so nothing secret
is typed or shown on screen (useful when recording a demo).

Usage:
  python -m scripts.admin health
  python -m scripts.admin credits
  python -m scripts.admin jobs
  python -m scripts.admin discover openai.com --include "VP" "Head" --exclude "Assistant"
  python -m scripts.admin enrich-company <id> [--force]
  python -m scripts.admin enrich-contact <id> [--force]
"""

import argparse
import json
import os
import sys

import httpx
from dotenv import load_dotenv


def admin_key() -> str:
    from app.config import settings

    return settings.admin_api_key.get_secret_value()


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Admin client for the enrichment service")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("health", "credits", "jobs"):
        commands.add_parser(name)
    discover = commands.add_parser("discover", help="title-filter preview (1 Forager credit, no writes)")
    discover.add_argument("domain")
    discover.add_argument("--include", nargs="*", default=None)
    discover.add_argument("--exclude", nargs="*", default=None)
    discover.add_argument("--limit", type=int, default=10)
    for name in ("enrich-company", "enrich-contact"):
        command = commands.add_parser(name)
        command.add_argument("object_id")
        command.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    base_url = os.environ.get("SERVICE_URL", "").rstrip("/")
    if not base_url:
        raise SystemExit("Set SERVICE_URL (e.g. in .env) to the service base URL")
    headers = {"X-Admin-Key": admin_key()}

    with httpx.Client(base_url=base_url, headers=headers, timeout=300) as client:
        if args.command == "health":
            response = client.get("/health")
        elif args.command == "credits":
            response = client.get("/admin/credits")
        elif args.command == "jobs":
            response = client.get("/admin/jobs", params={"limit": 10})
        elif args.command == "discover":
            payload = {"domain": args.domain, "limit": args.limit}
            if args.include is not None:
                payload["include_titles"] = args.include
            if args.exclude is not None:
                payload["exclude_titles"] = args.exclude
            response = client.post("/admin/discover", json=payload)
        else:
            kind = "company" if args.command == "enrich-company" else "contact"
            params = {"force": "true"} if args.force else {}
            response = client.post(f"/admin/enrich/{kind}/{args.object_id}", params=params)

    print(f"HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        print(response.text)
        return
    if args.command == "discover" and response.is_success:
        print(f"Filter: {data['filter']}")
        for i, candidate in enumerate(data.get("candidates", []), 1):
            print(f"{i:>2}. {candidate.get('job_title')!s:<45} {candidate.get('name')!s:<28} {candidate.get('linkedin_url')}")
        return
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
