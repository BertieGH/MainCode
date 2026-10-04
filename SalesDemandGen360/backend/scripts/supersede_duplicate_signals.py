"""Mark signals already stored twice as repeats of the first.

Extraction now recognises the same fact read from the same page, however it was
quoted (`extraction.same_fact`). Signals written before that rule existed are
still in the database twice. This walks every account's signals oldest first,
applies the same rule, and points each later copy at the one it repeats through
`superseded_by`.

Never a delete. A signal can be cited by a context version or a strategy, and a
row that disappears takes that citation with it. A superseded row stays, stops
counting — `context.live_signals` and the Signals tab both skip it — and says
which row it repeats.

**Ongoing themes** get a second pass: for a theme-kind type, one live reading
per account and person — the newest — and every older live reading points at it.

Idempotent: a row already superseded is left as it is.

    python scripts/supersede_duplicate_signals.py            # show what would change
    python scripts/supersede_duplicate_signals.py --apply    # write it
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.account import Account  # noqa: E402
from app.models.config import SignalType  # noqa: E402
from app.models.signal import Evidence, Signal, signal_evidence  # noqa: E402
from app.services.extraction import (  # noqa: E402
    SAME_FACT_SIMILARITY,
    HeldFact,
    _fact_key,
    page_of,
    same_fact,
    similarity,
    words_of,
)


async def main(apply: bool) -> None:
    async with SessionLocal() as session:
        signals = list(
            (
                await session.execute(
                    select(Signal).order_by(Signal.account_id, Signal.created_at)
                )
            ).scalars()
        )
        cited = await session.execute(
            select(signal_evidence.c.signal_id, Evidence.id, Evidence.source_url).join(
                Evidence, Evidence.id == signal_evidence.c.evidence_id
            )
        )
        ids: dict[uuid.UUID, set[uuid.UUID]] = {}
        pages: dict[uuid.UUID, set[str]] = {}
        for signal_id, evidence_id, url in cited.all():
            ids.setdefault(signal_id, set()).add(evidence_id)
            if (page := page_of(url)) is not None:
                pages.setdefault(signal_id, set()).add(page)

        names = dict((await session.execute(select(Account.id, Account.name))).all())

        # Per account and fact key: the originals seen so far, oldest first.
        seen: dict[tuple, list[tuple[Signal, HeldFact]]] = {}
        repeats: list[tuple[Signal, Signal]] = []
        for s in signals:
            fact = HeldFact(
                evidence_ids=ids.get(s.id, set()),
                pages=pages.get(s.id, set()),
                words=words_of(s.summary),
            )
            key = (s.account_id, *_fact_key(s))
            # Stricter than extraction, on purpose: history is only marked when
            # the summaries agree as well. Two rows citing one passage can still
            # say different things — BlueWave's "appointed a CRO" beside
            # "acquired CloudZen and appointed executives" — and superseding the
            # second after the fact would quietly lose the acquisition.
            original = next(
                (
                    row
                    for row, held in seen.get(key, [])
                    if same_fact(
                        held, evidence_ids=fact.evidence_ids, pages=fact.pages, words=fact.words
                    )
                    and similarity(held.words, fact.words) >= SAME_FACT_SIMILARITY
                ),
                None,
            )
            if original is None:
                seen.setdefault(key, []).append((s, fact))
                continue
            if s.superseded_by is None:
                repeats.append((s, original))

        for repeat, original in repeats:
            print(
                f"{names.get(repeat.account_id, repeat.account_id)} · {repeat.signal_type} · "
                f"{repeat.observed_at}\n"
                f"    keep     {original.created_at:%d %b %H:%M}  {original.summary[:90]}\n"
                f"    repeat   {repeat.created_at:%d %b %H:%M}  {repeat.summary[:90]}"
            )
            if apply:
                repeat.superseded_by = original.id

        # Ongoing themes: the newest live reading stands, the older ones point
        # at it. Rows the pass above just marked are already out of the running.
        theme_keys = {
            t.key
            for t in (
                await session.execute(select(SignalType).where(SignalType.kind == "theme"))
            ).scalars()
        }
        repeated = {r.id for r, _ in repeats}
        live = [
            s for s in signals
            if s.signal_type in theme_keys and s.superseded_by is None and s.id not in repeated
        ]
        newest: dict[tuple, Signal] = {}
        for s in sorted(live, key=lambda s: (s.observed_at, s.created_at), reverse=True):
            newest.setdefault((s.account_id, s.signal_type, s.contact_id), s)
        older = [
            (s, newest[(s.account_id, s.signal_type, s.contact_id)])
            for s in live
            if newest[(s.account_id, s.signal_type, s.contact_id)] is not s
        ]
        for stale, current in older:
            print(
                f"{names.get(stale.account_id, stale.account_id)} · {stale.signal_type} (theme)\n"
                f"    current  {current.observed_at}  {current.summary[:90]}\n"
                f"    older    {stale.observed_at}  {stale.summary[:90]}"
            )
            if apply:
                stale.superseded_by = current.id

        print(f"\n{len(repeats)} repeat(s) found")
        print(f"{len(older)} older theme reading(s) found")
        if apply:
            await session.commit()
            print("written.")
        else:
            print("dry run — pass --apply to write")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
