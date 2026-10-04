"""Demo mode: the whole application, none of the accounts.

A client evaluating this product should be able to walk every screen without an
Anthropic account, a ContactOut contract and a La Growth Machine seat. That is
the entire purpose of this module.

**Slots are satisfied by named stubs, not by fake credentials.** The obvious
implementation — write rows into `integration_credential` with
`status='valid'` — is the one to avoid. That column means "a live round-trip
succeeded", it is the single thing the setup gate trusts, and fabricating it
once to unlock a menu makes it untrustworthy everywhere, including in
production, where somebody will eventually debug a real outage by reading it.
So demo mode satisfies the slots directly and the credential table stays
truthful.

**Demo mode makes egress impossible, not merely unnecessary.** The dangerous
version of this feature is one where the gate opens and the code paths behind
it still reach for a real client — a demo that quietly bills an API, or worse,
sends a real message to a real prospect. So the outbound seams refuse by
construction: `assert_no_egress` is called *before* a client is built, not
after a request fails.

**Everything produced is stamped.** `run.mode` records which mode created a
run, and evidence, signals, context, qualification and strategy all carry
`run_id`. Without that, a demo and a real book become indistinguishable the
moment somebody switches to production, and the citation chain — the thing the
whole system is built to protect — silently stops meaning anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Run
from app.models.config import InstallationMode
from app.services.provider_catalogue import Kind

log = logging.getLogger(__name__)

PRODUCTION = "production"
DEMO = "demo"
MODES = (PRODUCTION, DEMO)


class EgressBlockedError(RuntimeError):
    """Something tried to reach a real external service in demo mode.

    Raised rather than silently stubbed. A demo that pretends a send happened
    teaches the client something false about the product, and a demo that
    quietly bills a real API is worse. Both are better as a visible refusal
    naming what was attempted.
    """

    def __init__(self, what: str):
        self.what = what
        super().__init__(
            f"{what} was attempted while this installation is in demo mode. "
            "Demo mode never contacts an external service. Switch to production "
            "on the Setup screen and connect real credentials."
        )


@dataclass(frozen=True)
class DemoProvider:
    """A stub that stands in for a real vendor, and says so."""

    key: str
    label: str
    kind: Kind
    detail: str


#: One per mandatory slot. Named `demo_*` so they can never collide with a real
#: provider key, and so a glance at any screen shows what is standing in.
DEMO_PROVIDERS: tuple[DemoProvider, ...] = (
    DemoProvider(
        "demo_enrichment",
        "Demo enrichment (stub)",
        "enrichment",
        "Returns fixture contacts. No provider is contacted and nothing is billed.",
    ),
    DemoProvider(
        "demo_llm",
        "Demo model (stub)",
        "llm",
        "Returns fixture analysis. No model is called and nothing is billed.",
    ),
    DemoProvider(
        "demo_outreach",
        "Demo delivery (stub)",
        "outreach",
        "Records what would have been sent. Nothing leaves this machine.",
    ),
)

BY_KIND: dict[Kind, DemoProvider] = {p.kind: p for p in DEMO_PROVIDERS}


async def current_mode(session: AsyncSession) -> str:
    """The active mode, defaulting to production.

    A missing row means an installation older than this feature, and the safe
    reading of "we do not know" is the strict one. Defaulting to demo would
    unlock the setup gate on a live book.
    """
    row = (
        await session.execute(
            select(InstallationMode.mode).where(InstallationMode.is_active.is_(True))
        )
    ).scalar_one_or_none()
    return row or PRODUCTION


async def is_demo(session: AsyncSession) -> bool:
    return await current_mode(session) == DEMO


async def demo_run_count(session: AsyncSession) -> int:
    """How many runs were produced in demo mode.

    Asked when switching to production. Demo evidence and demo signals sitting
    alongside real ones is not a cosmetic problem: every downstream claim cites
    evidence, and a book where some of those citations are fixtures cannot be
    trusted by the rep reading it.
    """
    return int(
        (
            await session.execute(
                select(func.count()).select_from(Run).where(Run.mode == DEMO)
            )
        ).scalar_one()
    )


def assert_no_egress(mode: str, what: str) -> None:
    """Refuse an outbound call while in demo mode.

    Called at each seam *before* a client is constructed. Checking afterwards —
    or relying on there being no credential — leaves the behaviour dependent on
    configuration that somebody can change, which is exactly the accident this
    prevents: a demo installation that still holds a working key would happily
    spend it.
    """
    if mode == DEMO:
        log.warning("demo.egress_blocked what=%s", what)
        raise EgressBlockedError(what)
