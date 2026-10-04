"""The CRM boundary.

CGVAK's CRM is custom and its API spec is still outstanding (`docs/07 Q2`), so
what exists here is the interface plus a stub. That is deliberate rather than a
placeholder: the interface is where the guarantee lives, and it can be settled
before the transport is.

Two properties are structural, not conventional:

* **There is no update and no delete.** `docs/02 §10` says CRM writes are
  create/append only. A method that overwrites a field cannot be called if the
  protocol does not declare one, so a future adapter cannot quietly acquire the
  ability by being careless.
* **The CRM is never exposed to the LLM.** No tool wraps this. A model that can
  read the CRM can be induced to read it by a prompt injected into a scraped
  page, and CRM notes are exactly the kind of confidential text that must not
  leave on someone else's instruction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CrmAccount:
    """What the CRM already knows. Authoritative over anything researched."""

    crm_id: str
    name: str
    domain: str | None = None
    owner: str | None = None
    status: str | None = None
    #: Free text the reps have written. Untrusted content: it is data for a
    #: prompt, never instructions in one.
    notes: tuple[str, ...] = ()
    last_activity_at: datetime | None = None


@dataclass(frozen=True)
class CrmContact:
    crm_id: str
    full_name: str
    title: str | None = None
    email: str | None = None
    linkedin_url: str | None = None


@runtime_checkable
class CrmAdapter(Protocol):
    """Read, create, append. Nothing else, on purpose."""

    async def find_account(self, *, domain: str | None, name: str) -> CrmAccount | None:
        """Look up an existing account. `None` means genuinely absent.

        An implementation that cannot reach the CRM must raise, not return
        None: "not in the CRM" and "we could not ask" lead to opposite actions,
        and conflating them is how a live customer gets prospected cold.
        """
        ...

    async def contacts_for(self, crm_id: str) -> list[CrmContact]: ...

    async def create_account(self, *, name: str, domain: str | None) -> CrmAccount: ...

    async def append_note(self, crm_id: str, note: str) -> None:
        """Append only. There is deliberately no way to edit or remove a note."""
        ...


class CrmUnavailableError(RuntimeError):
    """The CRM could not be reached. Distinct from 'the account is not there'."""


@dataclass
class StubCrmAdapter:
    """In-memory stand-in, until CGVAK's API spec lands.

    Faithful about the one thing that matters for correctness now: it
    distinguishes absence from unavailability, so code written against it
    cannot come to rely on the two looking alike.
    """

    accounts: dict[str, CrmAccount] = field(default_factory=dict)
    contacts: dict[str, list[CrmContact]] = field(default_factory=dict)
    notes: dict[str, list[str]] = field(default_factory=dict)
    #: Flip on to exercise the unavailable path.
    available: bool = True

    @staticmethod
    def _key(domain: str | None, name: str) -> str:
        return (domain or name).strip().upper()

    async def find_account(self, *, domain: str | None, name: str) -> CrmAccount | None:
        if not self.available:
            raise CrmUnavailableError("stub CRM marked unavailable")
        return self.accounts.get(self._key(domain, name))

    async def contacts_for(self, crm_id: str) -> list[CrmContact]:
        if not self.available:
            raise CrmUnavailableError("stub CRM marked unavailable")
        return list(self.contacts.get(crm_id, []))

    async def create_account(self, *, name: str, domain: str | None) -> CrmAccount:
        if not self.available:
            raise CrmUnavailableError("stub CRM marked unavailable")
        account = CrmAccount(crm_id=str(uuid.uuid4()), name=name, domain=domain)
        self.accounts[self._key(domain, name)] = account
        return account

    async def append_note(self, crm_id: str, note: str) -> None:
        if not self.available:
            raise CrmUnavailableError("stub CRM marked unavailable")
        self.notes.setdefault(crm_id, []).append(
            f"[{datetime.now(UTC).isoformat()}] {note}"
        )
