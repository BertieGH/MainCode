"""Swap the rep-made `linkedin_profile` source for the builtin `linkedin` one.

`linkedin_profile` asked research to "browse direct", which it may not do, and
stored nothing from linkedin.com in fifteen runs. This:

* pauses `linkedin_profile` — paused, not retired, so it can be resumed;
* puts `linkedin` in its place in the Default ICP's sources, as a new version;
* adds `linkedin` to what `public_focus` (company posts) and
  `public_pain_statement` (a person's posts) expect, so an empty LinkedIn search
  is reported as a gap in those conclusions.

Idempotent: run it twice and the second run changes nothing.

    python scripts/use_linkedin_source.py            # show what would change
    python scripts/use_linkedin_source.py --apply    # write it
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.config import (  # noqa: E402
    IcpProfile,
    IcpProfileVersion,
    ResearchSource,
    SignalType,
)

NEW, OLD = "linkedin", "linkedin_profile"
EXPECTED_BY = ("public_focus", "public_pain_statement")


async def main(apply: bool) -> None:
    async with SessionLocal() as session:
        sources = {
            s.key: s for s in (await session.execute(select(ResearchSource))).scalars()
        }
        if NEW not in sources:
            print(f"no {NEW!r} source — run `alembic upgrade head` first")
            return
        notes: list[str] = []

        old = sources.get(OLD)
        if old is None:
            notes.append(f"{OLD}: not present")
        elif old.status != "active":
            notes.append(f"{OLD}: already {old.status}")
        else:
            notes.append(f"{OLD}: paused")
            if apply:
                old.status = "paused"

        for key in EXPECTED_BY:
            row = (
                await session.execute(select(SignalType).where(SignalType.key == key))
            ).scalar_one_or_none()
            if row is None:
                notes.append(f"{key}: not found")
            elif NEW in (row.produced_by or []):
                notes.append(f"{key}: already expects {NEW}")
            else:
                notes.append(f"{key}: {NEW} added to {list(row.produced_by or [])}")
                if apply:
                    row.produced_by = [*(row.produced_by or []), NEW]

        profile = (
            await session.execute(select(IcpProfile).where(IcpProfile.name == "Default"))
        ).scalar_one_or_none()
        if profile is None:
            notes.append("ICP: no ICP named 'Default'")
        else:
            active = (
                await session.execute(
                    select(IcpProfileVersion).where(
                        IcpProfileVersion.icp_profile_id == profile.id,
                        IcpProfileVersion.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            definition = dict(active.definition if active else {})
            current = definition.get("sources")
            if current is None:
                notes.append("ICP: no accepted sources; it reads what its signal types name")
            else:
                wanted = [NEW if k == OLD else k for k in current]
                if NEW not in wanted:
                    wanted.append(NEW)
                wanted = list(dict.fromkeys(wanted))
                if wanted == current:
                    notes.append(f"ICP: already reads {NEW}")
                else:
                    notes.append(
                        f"ICP v{(active.version if active else 0) + 1}: {OLD} → {NEW} in its sources"
                    )
                    if apply:
                        definition["sources"] = wanted
                        if active is not None:
                            active.is_active = False
                            await session.flush()
                        session.add(
                            IcpProfileVersion(
                                icp_profile_id=profile.id,
                                definition=definition,
                                version=(active.version if active else 0) + 1,
                                is_active=True,
                            )
                        )

        print("\n".join(notes))
        if apply:
            await session.commit()
            print("\nwritten.")
        else:
            print("\ndry run — pass --apply to write")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
