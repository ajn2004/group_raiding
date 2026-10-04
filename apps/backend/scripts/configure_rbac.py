"""Replace one community's Discord role-to-capability mapping from JSON."""
import argparse
import json
from pathlib import Path

from sqlalchemy import delete

from app.api.authorization import CAPABILITIES
from app.api.auth_repository import ensure_community
from app.db.database import session_scope
from app.db.models import DiscordRoleCapability


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping_file", type=Path)
    args = parser.parse_args()
    config = json.loads(args.mapping_file.read_text())
    guild_id = str(config["guild_id"])
    mappings = config["mappings"]
    normalized = set()
    for item in mappings:
        role_id = str(item["role_id"])
        for capability in item["capabilities"]:
            if capability not in CAPABILITIES:
                raise ValueError(f"Unsupported capability: {capability}")
            normalized.add((role_id, capability))
    with session_scope() as db:
        community = ensure_community(db, guild_id)
        community.key = config.get("community", community.key)
        community_key = community.key
        db.execute(delete(DiscordRoleCapability).where(DiscordRoleCapability.community_id == community.id))
        db.add_all(DiscordRoleCapability(community_id=community.id, discord_role_id=role_id,
                                         capability=capability)
                   for role_id, capability in sorted(normalized))
        db.commit()
    print(f"Configured {len(normalized)} mappings for community {community_key!r}.")


if __name__ == "__main__":
    main()
