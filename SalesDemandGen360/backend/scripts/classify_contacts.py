"""Fill seniority and buying role from each contact's title.

New contacts are classified as they are written (`models/account.fill_role_from_title`).
This backfills the ones imported before that existed. It fills only blanks,
never overwriting a role a rep or research set.

    python scripts/classify_contacts.py           # show what would change
    python scripts/classify_contacts.py --apply   # write it
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402,F401  — sets the Windows event-loop policy
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.account import Contact, fill_role_from_title  # noqa: E402


async def _main(apply: bool) -> None:
    async with SessionLocal() as session:
        contacts = (await session.execute(select(Contact))).scalars().all()
        changed: Counter = Counter()
        for c in contacts:
            before = (c.seniority, c.buying_role)
            fill_role_from_title(c)
            after = (c.seniority, c.buying_role)
            if before != after:
                changed[(after[0], after[1] or "-")] += 1
        total = sum(changed.values())
        print(f"{total} of {len(contacts)} contacts gain a classification:")
        for (seniority, role), n in changed.most_common():
            print(f"  {n:>4}  {seniority:<9} {role}")
        if apply:
            await session.commit()
            print("Written.")
        else:
            await session.rollback()
            print("Nothing written — pass --apply to write it.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true")
    asyncio.run(_main(parser.parse_args().apply))
