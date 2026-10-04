"""Put the job board to work: in the Default ICP, and expected by hiring.

The `job_board` source exists once migration c4e1a7d9f2b5 has run, but a source
only runs for a list when its ICP has accepted it — the ICP's source set is the
plan of record. This adds it to the Default ICP as a new version, and to the
sources `engineering_scaling` expects, so an empty board is reported as a gap in
that conclusion rather than as an anonymous extra.

Idempotent: run it twice and the second run changes nothing.

    python scripts/add_job_board_source.py            # show what would change
    python scripts/add_job_board_source.py --apply    # write it
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

KEY = "job_board"


async def main(apply: bool) -> None:
    async with SessionLocal() as session:
        source = (
            await session.execute(select(ResearchSource).where(ResearchSource.key == KEY))
        ).scalar_one_or_none()
        if source is None:
            print(f"no {KEY!r} source — run `alembic upgrade head` first")
            return

        scaling = (
            await session.execute(select(SignalType).where(SignalType.key == "engineering_scaling"))
        ).scalar_one_or_none()
        type_note = "engineering_scaling not found"
        if scaling is not None:
            if KEY in (scaling.produced_by or []):
                type_note = f"engineering_scaling already expects {KEY}"
            else:
                type_note = f"engineering_scaling: {KEY} added to {list(scaling.produced_by or [])}"
                if apply:
                    scaling.produced_by = [*(scaling.produced_by or []), KEY]

        profile = (
            await session.execute(select(IcpProfile).where(IcpProfile.name == "Default"))
        ).scalar_one_or_none()
        icp_note = "no ICP named 'Default'"
        if profile is not None:
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
                # No accepted set means research reads what the signal types
                # name, which now includes the job board — nothing to add here.
                icp_note = "ICP has no accepted sources; it reads what its signal types name"
            elif KEY in current:
                icp_note = f"ICP already reads {KEY}"
            else:
                icp_note = f"ICP v{(active.version if active else 0) + 1}: {KEY} added to its sources"
                if apply:
                    definition["sources"] = [*current, KEY]
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

        print(type_note)
        print("ICP:", icp_note)
        if apply:
            await session.commit()
            print("\nwritten.")
        else:
            print("\ndry run — pass --apply to write")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
