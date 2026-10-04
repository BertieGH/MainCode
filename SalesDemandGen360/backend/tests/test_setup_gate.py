"""The three mandatory connections, and what "ready" is allowed to mean.

A setup gate is only worth having if it cannot be satisfied by something that
does not work. Three ways to make it worthless, all tested here:

* counting a credential that merely **decrypts** — that proves `SECRET_KEY` is
  unchanged and nothing about the key;
* counting a key nobody can **check**, which is the same failure wearing a
  different hat;
* counting a key of the **wrong kind** — an Anthropic key does not make
  outreach possible. This is the easy mistake: with three slots and one
  credential table, a loop that forgets to check kind unlocks the whole
  application on one key.

The fourth case — a verified key on a vendor with no work adapter — is
deliberately **not** uniform, and both halves of that asymmetry are tested. For
`llm` it blocks, because an alternative exists today and letting it through
guarantees a runtime failure. For `enrichment` and `outreach` it passes with a
warning, because those adapters are tracked build work and blocking on them
would lock the application on something that is not credential configuration.
"""

from __future__ import annotations

import pytest

from app.services import readiness
from app.services.readiness import CredentialState, Slot


def _cred(
    provider="anthropic",
    label="Anthropic",
    status="valid",
    runnable=True,
    verifiable=True,
):
    return CredentialState(
        provider=provider,
        label=label,
        status=status,
        runnable=runnable,
        verifiable=verifiable,
    )


class TestWhatSatisfiesASlot:
    def test_a_verified_runnable_credential_satisfies_it(self):
        slot = Slot("llm", "Model provider", "why", [_cred()])
        assert slot.satisfied
        assert slot.state == "ready"
        assert slot.blocker is None

    def test_a_stored_but_untested_credential_does_not(self):
        """The whole point. A decrypt is not a round-trip."""
        slot = Slot("llm", "Model provider", "why", [_cred(status="untested")])
        assert not slot.satisfied
        assert slot.state == "unverified"
        assert "not verified" in slot.blocker

    def test_a_rejected_credential_does_not(self):
        slot = Slot("llm", "Model provider", "why", [_cred(status="invalid")])
        assert not slot.satisfied

    def test_a_verified_llm_key_with_no_model_adapter_does_not(self):
        """The key is real and verified. No stage can call it.

        The state somebody reaches by pasting a working OpenAI key. It blocks
        because an alternative exists today — telling them to add an Anthropic
        key is an instruction they can act on, and letting it through
        guarantees `NoAdapterError` on the first run.
        """
        slot = Slot(
            "llm", "Model provider", "why",
            [_cred(provider="openai", label="OpenAI", runnable=False)],
        )
        assert not slot.satisfied
        assert "no stage can run on it" in slot.blocker
        assert "Anthropic" in slot.blocker

    def test_a_verified_outreach_key_with_no_client_does_satisfy_but_warns(self):
        """Deliberately different from the LLM case.

        The LGM client is tracked build work (`docs/08` Phase 11). Blocking on
        it would lock the application on something that has nothing to do with
        configuring a credential — so the slot passes and the pending
        integration travels with it as a warning that never gates.
        """
        slot = Slot(
            "outreach", "Outreach delivery", "why",
            [_cred(provider="lgm", label="La Growth Machine", runnable=False)],
        )
        assert slot.satisfied
        assert slot.blocker is None
        assert "not built yet" in slot.warning

    def test_a_key_nobody_can_check_can_never_satisfy_a_slot(self):
        """Otherwise the gate passes on a decrypt, which is the whole failure."""
        slot = Slot(
            "enrichment", "Contact enrichment", "why",
            [_cred(provider="mystery", label="Mystery", status="untested",
                   runnable=False, verifiable=False)],
        )
        assert not slot.satisfied
        assert "can never" in slot.blocker

    def test_one_working_credential_is_enough_among_several(self):
        """A waterfall needs one provider, not all of them."""
        slot = Slot(
            "enrichment", "Contact enrichment", "why",
            [
                _cred(provider="contactout", label="ContactOut", status="invalid"),
                _cred(provider="apollo", label="Apollo.io", status="valid"),
            ],
        )
        assert slot.satisfied

    def test_an_empty_slot_says_nothing_is_configured(self):
        slot = Slot("outreach", "Outreach delivery", "why", [])
        assert slot.state == "missing"
        assert "No outreach delivery provider is configured" in slot.blocker


class TestTheThreeStatesAreDistinct:
    """"Not added" and "added but unverified" are different instructions.

    Collapsing them into "not ready" sends someone to add a second key when
    what they needed was to press Test on the one they have.
    """

    @pytest.mark.parametrize(
        ("creds", "expected"),
        [
            ([], "missing"),
            ([_cred(status="untested")], "unverified"),
            ([_cred(status="invalid")], "unverified"),
            ([_cred()], "ready"),
        ],
    )
    def test_state(self, creds, expected):
        assert Slot("llm", "t", "w", creds).state == expected


class TestReadinessOverall:
    def _readiness(self, **by_kind):
        return readiness.Readiness(
            slots=[
                Slot(kind, readiness.SLOT_COPY[kind][0], readiness.SLOT_COPY[kind][1],
                     by_kind.get(kind, []))
                for kind in ("enrichment", "llm", "outreach")
            ]
        )

    def test_all_three_are_required(self):
        state = self._readiness(
            enrichment=[_cred("contactout", "ContactOut")],
            llm=[_cred()],
        )
        assert not state.ready
        assert len(state.blockers) == 1

    def test_ready_when_every_slot_is_satisfied(self):
        state = self._readiness(
            enrichment=[_cred("contactout", "ContactOut")],
            llm=[_cred()],
            outreach=[_cred("lgm", "La Growth Machine")],
        )
        assert state.ready
        assert state.blockers == []

    def test_every_blocker_is_reported_at_once(self):
        """Three round-trips through a screen nobody wanted to visit, otherwise."""
        assert len(self._readiness().blockers) == 3

    async def test_require_ready_raises_carrying_every_blocker(self):
        class _Empty:
            """A database with nothing in it: no credentials, no mode row.

            `scalar_one` returns 0 for the demo-run count; a missing mode row
            resolves to production, which is the safe default — see
            `demo.current_mode`.
            """

            async def execute(self, stmt):
                class _R:
                    def scalars(self):
                        return self

                    def __iter__(self):
                        return iter([])

                    def scalar_one_or_none(self):
                        return None

                    def scalar_one(self):
                        return 0

                return _R()

        with pytest.raises(readiness.NotReadyError) as exc:
            await readiness.require_ready(_Empty())
        blockers = exc.value.blockers
        # Three provider slots plus one configuration requirement. Credentials
        # are not the only precondition: a key connects you to a vendor without
        # telling it who to look for, so "no active service" belongs in the
        # same list rather than surfacing later as an empty enrichment run.
        assert len(blockers) == 4
        assert any("No active service" in b for b in blockers)


class TestAKeyCannotSatisfySomeoneElsesSlot:
    """One credential table, three slots — the easy mistake to make."""

    def test_the_catalogue_assigns_every_shipped_provider_exactly_one_kind(self):
        from app.services import provider_catalogue

        for provider in provider_catalogue.CATALOGUE:
            assert provider.kind in ("llm", "enrichment", "outreach", "crm")

    def test_anthropic_is_not_an_outreach_provider(self):
        from app.services import provider_catalogue

        assert provider_catalogue.kind_of("anthropic") == "llm"
        assert provider_catalogue.kind_of("lgm") == "outreach"
        assert provider_catalogue.kind_of("contactout") == "enrichment"

    def test_a_provider_nobody_ships_has_no_kind_and_so_satisfies_nothing(self):
        from app.services import provider_catalogue

        assert provider_catalogue.kind_of("mistral") is None

    def test_the_crm_is_not_a_mandatory_slot(self):
        """A missing CRM makes the pipeline cautious, not broken.

        Research halts rather than prospecting blind into an existing customer,
        which is a degraded state and not a reason to lock the application.
        """
        from app.services.provider_catalogue import MANDATORY_KINDS

        assert "crm" not in MANDATORY_KINDS
        assert set(MANDATORY_KINDS) == {"enrichment", "llm", "outreach"}


class TestACredentialNobodyCanSeeCannotBeDeleted:
    """An unclassifiable provider must still reach the screen.

    Provider names are typeable, so `appollo` is one keystroke from `apollo`.
    The row is then stored and encrypted, has no catalogue entry, no probe, and
    no slot — and every screen renders credentials *through* a slot. So it
    rendered nowhere: a live secret in the database with no way to remove it
    short of SQL, on a screen whose whole job is managing credentials.

    Keeping it out of `by_kind` is right and is tested above — an unrelated key
    must never unlock the application. Dropping it from the response entirely
    is the part that was wrong.
    """

    def test_an_unrecognised_provider_is_reported_not_swallowed(self):
        import inspect

        source = inspect.getsource(readiness.evaluate)
        # It is appended before the `continue` that keeps it out of the slots.
        assert "unrecognised.append(state)" in source
        assert "unrecognised=unrecognised" in source

    def test_readiness_carries_a_place_to_put_them(self):
        state = readiness.Readiness()
        assert state.unrecognised == []

    def test_an_unrecognised_credential_still_satisfies_nothing(self):
        """Visible is not the same as counted. The gate is unchanged."""
        from app.services import provider_catalogue

        assert provider_catalogue.kind_of("appollo") is None
        state = readiness.Readiness(
            slots=[Slot("llm", "Model provider", "why", [])],
            unrecognised=[_cred(provider="appollo", label="appollo",
                                status="untested", runnable=False,
                                verifiable=False)],
        )
        assert not state.ready

    def test_the_api_hands_them_to_the_screen(self):
        import inspect

        from app.api import config as config_api

        source = inspect.getsource(config_api.get_readiness)
        assert "unrecognised=[" in source, (
            "readiness computes them and the endpoint drops them again"
        )


class TestRemovingACredential:
    """Adding freely is only half of it.

    Providers became user-addable, which means a typo becomes a permanent row
    unless it can be removed. A credential is a secret, not a record: no
    evidence, signal or execution row cites it, so there is nothing to protect
    by refusing.
    """

    async def test_removing_the_last_credential_re_closes_the_gate(self):
        """Readiness going backwards is the feature, not a bug.

        It is derived on every call precisely so it can follow the world down
        as well as up — a revoked key, a deleted credential, an exhausted
        account.
        """
        slot = Slot("outreach", "Outreach delivery", "why",
                    [_cred(provider="lgm", label="LGM", runnable=False)])
        assert slot.satisfied

        emptied = Slot("outreach", "Outreach delivery", "why", [])
        assert not emptied.satisfied
        assert emptied.state == "missing"

    def test_removing_one_of_several_leaves_the_slot_satisfied(self):
        """A waterfall keeps working while one provider is swapped out."""
        remaining = Slot(
            "enrichment", "Contact enrichment", "why",
            [_cred(provider="apollo", label="Apollo.io", runnable=False)],
        )
        assert remaining.satisfied


class TestTheBlockerMatchesTheActualState:
    """"Run Test again" is wrong advice for most ways a slot fails.

    Each of these needs a different action, and a single generic message sends
    people to the wrong one — which is worse than saying nothing, because they
    do it and it does not work.
    """

    def test_an_unbillable_account_is_not_told_to_re_test(self):
        slot = Slot("llm", "Model provider", "why", [_cred(status="expired")])
        assert not slot.satisfied
        assert "Re-testing will not change it" in slot.blocker
        assert "Run Test" not in slot.blocker

    def test_a_rejected_key_is_told_to_re_issue(self):
        slot = Slot("llm", "Model provider", "why", [_cred(status="invalid")])
        assert "Re-issue it" in slot.blocker

    def test_an_untested_key_is_told_to_test(self):
        slot = Slot("llm", "Model provider", "why", [_cred(status="untested")])
        assert "Run Test on it" in slot.blocker

    def test_a_mix_falls_back_to_the_generic_instruction(self):
        """One bad and one untested: testing the untested one is the next move."""
        slot = Slot(
            "enrichment", "Contact enrichment", "why",
            [
                _cred(provider="contactout", label="ContactOut", status="invalid"),
                _cred(provider="apollo", label="Apollo.io", status="untested"),
            ],
        )
        assert "Run Test on it" in slot.blocker


class TestTheAdapterListStaysTrueAsAdaptersLand:
    """The blocker names which providers work, not one of them by hand.

    Written when Anthropic was the only adapter; Gemini's arrival would have
    left it advising somebody to buy an Anthropic key they did not need.
    """

    def test_the_message_lists_every_runnable_model_provider(self):
        from app.services import provider_catalogue

        slot = Slot(
            "llm", "Model provider", "why",
            [_cred(provider="openai", label="OpenAI", runnable=False)],
        )
        blocker = slot.blocker
        for provider in provider_catalogue.of_kind("llm"):
            if provider.runnable:
                assert provider.label in blocker, provider.key
            else:
                # Naming a provider that cannot run anything as the fix would
                # send somebody to buy exactly the wrong key.
                assert f"adapters for {provider.label}" not in blocker
