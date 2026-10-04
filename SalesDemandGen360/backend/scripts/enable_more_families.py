"""Turn on the query families that already exist but nothing claimed.

Research runs the families the *active signal types* name in `produced_by`.
With five types configured, three families in the registry had no claimant and
therefore never ran: `news` (launches, partnerships, incidents), `tech_stack`,
and `reviews`. A fourth, `company_site`, was added with them.

This inserts the types that claim those families and adds them to the Default
ICP as a new version. Idempotent: run it twice and the second run changes
nothing.

    python scripts/enable_more_families.py            # show what would change
    python scripts/enable_more_families.py --apply    # write it
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.config import IcpProfile, IcpProfileVersion, SignalType  # noqa: E402

#: key, label, description, ttl days, weight, families it is produced by.
#:
#: Each one exists to make a family run, and each says what a rep would do
#: about it. A type nobody would act on is a coverage gap with extra steps.
NEW_TYPES = [
    (
        "product_launch", "Product launch or major release",
        "A launch, GA, or significant capability announced publicly. Release pressure is "
        "the moment quality work is bought.",
        120, 1.10, ["news", "company_site"],
    ),
    (
        "partnership", "Partnership or integration",
        "A partnership, integration or channel deal. New surface area to build and support.",
        180, 0.90, ["news"],
    ),
    (
        "tech_adoption", "Technology adopted",
        "A tool, platform or stack choice named publicly — in a job post, an engineering "
        "blog, or an integrations page. Says what the delivery environment actually is.",
        365, 1.00, ["tech_stack"],
    ),
    (
        "public_focus", "Public focus",
        "What the company is pushing right now, in its own posts and announcements. Weak as a "
        "buying trigger — deliberately low weight — but it is what earns a first line that "
        "proves we read them.",
        90, 0.60, ["company_site", "news"],
    ),
    (
        "delivery_quality_theme", "Delivery or quality theme",
        "A recurring theme about delivery, release quality or support — in reviews, or "
        "stated by the company itself. The problem this service is sold against.",
        180, 1.25, ["reviews", "company_site"],
    ),
]

#: Added to the Default ICP alongside what it already names.
ADD_TO_ICP = [t[0] for t in NEW_TYPES] + ["public_pain_statement"]

#: Ongoing states rather than dated events — one live signal each, moving forward.
THEMES = {"public_focus", "delivery_quality_theme"}


async def main(apply: bool) -> None:
    async with SessionLocal() as session:
        existing = {
            row.key for row in (await session.execute(select(SignalType))).scalars()
        }
        added = []
        for key, label, description, ttl, weight, produced_by in NEW_TYPES:
            if key in existing:
                continue
            added.append(key)
            if apply:
                session.add(
                    SignalType(
                        key=key, label=label, description=description, scope="company",
                        default_ttl_days=ttl, weight=weight, produced_by=produced_by,
                        status="active", kind="theme" if key in THEMES else "event",
                    )
                )

        profile = (
            await session.execute(select(IcpProfile).where(IcpProfile.name == "Default"))
        ).scalar_one_or_none()
        icp_note = "no ICP named 'Default' — nothing to update"
        if profile is not None:
            active = (
                await session.execute(
                    select(IcpProfileVersion).where(
                        IcpProfileVersion.icp_profile_id == profile.id,
                        IcpProfileVersion.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            current = list((active.definition if active else {}).get("signals_that_matter") or [])
            wanted = current + [k for k in ADD_TO_ICP if k not in current]
            if wanted == current:
                icp_note = f"ICP already names all {len(current)} types"
            else:
                icp_note = (
                    f"ICP v{(active.version if active else 0) + 1}: "
                    f"{', '.join(k for k in wanted if k not in current)} added to "
                    f"{len(current)} already there"
                )
                if apply:
                    definition = dict(active.definition if active else {})
                    definition["signals_that_matter"] = wanted
                    if active is not None:
                        # Versioned, never edited: an enrichment or research run
                        # records which version it read, and rewriting one would
                        # make "why were these chosen?" unanswerable.
                        active.is_active = False
                    session.add(
                        IcpProfileVersion(
                            icp_profile_id=profile.id,
                            definition=definition,
                            version=(active.version if active else 0) + 1,
                            is_active=True,
                        )
                    )

        print("signal types added:", ", ".join(added) or "(none — already present)")
        print("ICP:", icp_note)
        if apply:
            await session.commit()
            print("\nwritten.")
        else:
            print("\ndry run — pass --apply to write")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
