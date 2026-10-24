"""Create the forager_* custom properties in HubSpot (idempotent, no Forager calls).

Usage: python -m scripts.setup_hubspot_properties [--include-extra-fields]
"""

import argparse
import asyncio

from app.clients.hubspot import HubSpotClient
from app.config import settings
from app.hubspot_properties import ensure_properties


async def main(include_extra_fields: bool) -> None:
    hubspot = HubSpotClient(settings.hubspot_access_token.get_secret_value())
    try:
        created = await ensure_properties(hubspot, include_extra_fields=include_extra_fields)
    finally:
        await hubspot.aclose()
    for object_type, names in created.items():
        print(f"{object_type}: created {len(names)} {names if names else '(all present)'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-extra-fields",
        action="store_true",
        help="also create the nice-to-have fields flagged for discussion (headline, About, skills)",
    )
    asyncio.run(main(parser.parse_args().include_extra_fields))
