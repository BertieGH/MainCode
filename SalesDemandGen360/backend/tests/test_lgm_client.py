"""The live La Growth Machine client: what it sends, and what it refuses.

Nothing here touches the network — every request is answered by a stubbed
transport, and what is asserted is the shape of what we would have sent. That
is the interesting part: this is the one client that can put a message in front
of a person, and three of its behaviours are the provider's, not ours.

* Enrolment is audience membership. There is no enrol call to make.
* Ten attributes of 1000 characters, silently truncated beyond that.
* A rejection body quotes the request back, so no body reaches an error string.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest

from app.services.lgm import LgmError
from app.services.lgm_client import LgmPerson, LiveLgmAdapter, check_shape, split_name

CAMPAIGN = "64b66c65495202b18a05edfe"


@dataclass
class Fake:
    """A stand-in LGM, recording every request it is sent."""

    status: str = "RUNNING"
    steps: tuple[dict, ...] = ()
    audience: tuple[str, str] = ("aud-1", "Gen360 · Standard")
    lead_status: int = 200
    seen: list[httpx.Request] = None  # type: ignore[assignment]

    def __post_init__(self):
        self.seen = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if path.endswith("/members"):
            return httpx.Response(200, json={"statusCode": 200, "members": [{"id": "m1"}]})
        if path.endswith("/messages"):
            return httpx.Response(200, json={"statusCode": 200, "data": list(self.steps)})
        if path.endswith(f"/campaigns/{CAMPAIGN}"):
            return httpx.Response(200, json={"statusCode": 200, "campaign": {
                "id": CAMPAIGN, "status": self.status, "modifiedAt": 1700461831358,
                "channels": ["LINKEDIN", "EMAIL"],
                "audience": {"id": self.audience[0], "name": self.audience[1]},
            }})
        if path.endswith("/leads"):
            return httpx.Response(200, json={"statusCode": 200, "lead": {"id": "lead-77"}})
        if path.endswith("/leads/status"):
            return httpx.Response(self.lead_status, json={"statusCode": self.lead_status, "logs": []})
        if path.endswith("/settings"):
            return httpx.Response(200, json={"statusCode": 200, "campaign": {"id": CAMPAIGN}})
        if path.endswith("/removefromaudience"):
            return httpx.Response(200, json={"statusCode": 200})
        if path.endswith("/status"):
            return httpx.Response(200, json={"statusCode": 200, "data": {"status": "PAUSED"}})
        return httpx.Response(404, json={"error": "no such route"})


def build(fake: Fake) -> LiveLgmAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    return LiveLgmAdapter("secret-key", client=client)


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content.decode())


class TestWhatIsSent:
    async def test_the_key_travels_in_a_header_and_never_in_the_url(self):
        fake = Fake()
        assert await build(fake).members() == [{"id": "m1"}]
        [request] = fake.seen
        assert request.headers["authorization"] == "Bearer secret-key"
        assert "secret-key" not in str(request.url)

    async def test_a_lead_carries_its_audience_its_copy_and_our_contact_id(self):
        fake = Fake()
        lead = await build(fake).upsert_lead(
            email="enrico@datadoghq.com",
            linkedin_url=None,
            attributes={"custom_attribute_1": "Hello", "custom_attribute_2": "Following up"},
            audience="Gen360 · Standard",
            person=LgmPerson(
                first_name="Enrico", last_name="Bergamo", company_name="Datadog",
                job_title="CTO", crm_id="contact-123",
            ),
        )
        assert lead.lead_id == "lead-77"
        sent = body_of(fake.seen[-1])
        assert sent["audience"] == "Gen360 · Standard", "the audience is the enrolment"
        assert sent["proEmail"] == "enrico@datadoghq.com"
        assert (sent["firstname"], sent["lastname"]) == ("Enrico", "Bergamo")
        assert sent["crm_id"] == "contact-123", "the join key for everything that comes back"
        # LGM's spelling, not ours. This asserted `custom_attribute_1` for
        # months and passed, because the stub accepts any key — while every
        # real enrolment was rejected with a 404 for the unknown field.
        assert sent["customAttribute1"] == "Hello"
        assert sent["customAttribute2"] == "Following up"
        assert "custom_attribute_1" not in sent

    async def test_our_attribute_names_are_translated_at_the_boundary(self):
        """Two vocabularies met here and nobody translated between them.

        Everything inside Gen360 says `custom_attribute_7`; LGM's lead payload
        only knows `customAttribute7`, and answers an unknown field with the
        404 it also uses for a missing route. Every enrolment failed that way.
        """
        from app.services.lgm import wire_attribute

        assert wire_attribute("custom_attribute_1") == "customAttribute1"
        assert wire_attribute("custom_attribute_20") == "customAttribute20"
        assert wire_attribute("customAttribute3") == "customAttribute3", "already in LGM's spelling"

    async def test_a_name_lgm_does_not_know_is_refused_rather_than_sent(self):
        """Execution used to invent `custom_attribute_1_subject` for a subject
        line. One unknown field loses the whole lead, body included — so it is
        refused here, with a sentence, instead of there, with a status code."""
        from app.services.lgm import wire_attribute

        with pytest.raises(LgmError, match="customAttribute1 to customAttribute20"):
            wire_attribute("custom_attribute_1_subject")

        fake = Fake()
        with pytest.raises(LgmError):
            await build(fake).upsert_lead(
                email="a@b.com", linkedin_url=None,
                attributes={"custom_attribute_1_subject": "Quick question"},
            )
        assert fake.seen == [], "nothing was sent"

    async def test_a_touch_too_long_for_an_attribute_is_refused_before_it_is_written(self):
        fake = Fake()
        with pytest.raises(LgmError, match="1000 per attribute"):
            await build(fake).upsert_lead(
                email="a@b.com", linkedin_url=None,
                attributes={"custom_attribute_1": "x" * 1001},
            )
        assert fake.seen == [], "nothing was sent"

    async def test_somebody_with_no_way_to_be_matched_is_refused(self):
        with pytest.raises(LgmError, match="email, a LinkedIn URL, or a full name"):
            await build(Fake()).upsert_lead(email=None, linkedin_url=None, attributes={})

    def test_one_name_field_becomes_two(self):
        assert split_name("Enrico Bergamo") == ("Enrico", "Bergamo")
        assert split_name("Jon O") == ("Jon", "O")
        assert split_name(None) == ("", "")


class TestVerifyingACampaignBeforeItsFirstLaunch:
    async def test_never_launched_is_not_a_finding(self):
        """Otherwise nothing could ever be launched.

        A finding makes the check unsound, which withholds `verified_at`,
        which blocks enrolment for never having been verified — so the
        campaign cannot be filled, so it cannot be launched, so it stays
        READY. §41's deadlock in a different hat. Enrolment already says it
        plainly, as a warning.
        """
        fake = Fake(status="READY", steps=(step(0, "customAttribute1"), step(1, "customAttribute2")))
        check = await check_shape(build(fake), shape())
        assert check.status == "ready"
        assert check.sound, check.findings

    async def test_paused_is_still_a_finding(self):
        fake = Fake(status="PAUSED", steps=(step(0, "customAttribute1"), step(1, "customAttribute2")))
        check = await check_shape(build(fake), shape())
        assert not check.sound and "paused" in check.findings[0]


class TestWhereAStepSitsInTheCampaign:
    """`/messages` cannot see most of a campaign.

    It returns templates and an order among templates. `/campaigns/:id/steps`
    — undocumented — returns the campaign's real steps, and on the first
    account this was read against the two message templates sat at positions
    **4 and 5**: three earlier steps (a profile visit, a connection request, a
    wait) carry nothing of ours and are invisible to `/messages` entirely. So
    "step 1" in Gen360 was never step 1 over there.
    """

    async def test_position_and_name_come_from_the_steps_route(self):
        from app.services.lgm_client import read_templates

        templates = [
            {"id": "tpl-a", "order": 0, "channel": "GOOGLE", "active": True,
             "contentHtml": "{{customAttribute3}}", "subjectHtml": "{{customAttribute2}}"},
            {"id": "tpl-b", "order": 1, "channel": "LINKEDIN", "active": True,
             "contentHtml": "{{customAttribute1}}", "subjectHtml": ""},
        ]
        steps = [
            {"templateId": "tpl-a", "position": 4, "type": "GOOGLE_SEND_EMAIL",
             "templateName": "Not Accepted - Email"},
            {"templateId": "tpl-b", "position": 5, "type": "LINKEDIN_DIRECT_MESSAGE",
             "templateName": "Accepted - DM"},
        ]
        read = read_templates(templates, steps)
        assert read.step_meta[1]["position"] == 4
        assert read.step_meta[1]["name"] == "Not Accepted - Email"
        assert read.step_meta[2]["name"] == "Accepted - DM", (
            "the name is the only place a branch announces itself as one"
        )

    async def test_the_mapping_survives_without_the_steps_route(self):
        """It is undocumented, so a plan or an older adapter may not serve it.
        Only the labelling is poorer."""
        from app.services.lgm_client import read_templates

        read = read_templates(
            [{"id": "tpl-a", "order": 0, "channel": "GOOGLE", "active": True,
              "contentHtml": "{{customAttribute3}}", "subjectHtml": ""}],
            [],
        )
        assert read.body_by_step == {1: "custom_attribute_3"}
        assert read.step_meta == {}

    async def test_steps_are_matched_by_template_not_by_order(self):
        """Neither list promises the same order as the other."""
        from app.services.lgm_client import read_templates

        templates = [
            {"id": "tpl-a", "order": 0, "channel": "GOOGLE", "active": True,
             "contentHtml": "{{customAttribute1}}", "subjectHtml": ""},
            {"id": "tpl-b", "order": 1, "channel": "LINKEDIN", "active": True,
             "contentHtml": "{{customAttribute2}}", "subjectHtml": ""},
        ]
        steps = [
            {"templateId": "tpl-b", "position": 9, "templateName": "second"},
            {"templateId": "tpl-a", "position": 2, "templateName": "first"},
        ]
        read = read_templates(templates, steps)
        assert read.step_meta[1]["name"] == "first"
        assert read.step_meta[2]["name"] == "second"


class TestGivingACampaignAnAudience:
    """The step that used to be "go and do it in the LGM app".

    A campaign with no audience cannot enrol anybody — membership of the
    audience *is* the enrolment — and `POST /campaigns/:id/settings` is how it
    is set. It reads as a missing route because probing it with a GET answers
    404; it only accepts POST.
    """

    async def test_a_ready_campaign_takes_the_audience(self):
        fake = Fake(status="READY")
        assert await build(fake).set_campaign_audience(CAMPAIGN, "aud-9") == "aud-9"
        post = [r for r in fake.seen if r.method == "POST"][-1]
        assert post.url.path.endswith(f"/campaigns/{CAMPAIGN}/settings")
        assert body_of(post) == {"audienceId": "aud-9"}

    async def test_a_launched_campaign_is_refused_before_the_write(self):
        """LGM fixes the audience at first launch. Checked here so the answer
        is a sentence rather than a 404 that looks like a missing endpoint."""
        fake = Fake(status="RUNNING")
        with pytest.raises(LgmError, match="before a campaign's first launch"):
            await build(fake).set_campaign_audience(CAMPAIGN, "aud-9")
        assert not [r for r in fake.seen if r.method == "POST"], "nothing was attempted"

    async def test_only_the_settings_named_are_sent(self):
        fake = Fake()
        await build(fake).update_campaign_settings(CAMPAIGN, name="Renamed")
        assert body_of(fake.seen[-1]) == {"name": "Renamed"}

    async def test_an_empty_update_is_refused(self):
        with pytest.raises(LgmError, match="nothing to update"):
            await build(Fake()).update_campaign_settings(CAMPAIGN)


class TestTakingSomebodyOutOfAnAudience:
    async def test_the_lead_is_removed_by_identifier(self):
        """Not a delete: absence from the audience is what un-enrols them,
        exactly as presence enrolled them."""
        fake = Fake()
        await build(fake).remove_from_audience(audience="Gen360 · Standard", proEmail="a@b.c")
        assert body_of(fake.seen[-1]) == {"audience": ["Gen360 · Standard"], "proEmail": "a@b.c"}

    async def test_removing_nobody_in_particular_is_refused(self):
        with pytest.raises(LgmError, match="needs an identifier"):
            await build(Fake()).remove_from_audience(audience="Gen360 · Standard")


class TestACampaignThatIsNoLongerThere:
    async def test_check_shape_reports_it_gone_rather_than_raising(self):
        """The registration has to be told, not just the caller.

        A campaign deleted in LGM answers 404 on every route. Letting that
        escape as an error would leave the stored row saying "verified" — so
        the check returns a verdict instead, and it is the verdict that clears
        the verification.
        """
        from app.services.lgm_client import STATUS_MISSING, check_shape

        class Gone:
            async def campaign_meta(self, campaign_id):
                raise LgmError(f"campaign {campaign_id} was not found in La Growth Machine")

        check = await check_shape(Gone(), shape())
        assert check.status == STATUS_MISSING
        assert not check.sound
        assert "no longer in the La Growth Machine account" in check.findings[0]


class TestEnrolmentIsMembership:
    async def test_a_running_campaign_returns_a_reference_without_a_second_call(self):
        fake = Fake(status="RUNNING")
        ref = await build(fake).enrol(lead_id="lead-77", lgm_campaign_id=CAMPAIGN)
        assert ref == f"{CAMPAIGN}:lead-77"
        assert [r.method for r in fake.seen] == ["GET"], "nothing is posted; membership enrolled them"

    async def test_a_campaign_never_launched_takes_the_lead_and_says_it_is_waiting(self):
        """This used to raise, and the two ends deadlocked.

        LGM will not launch a campaign whose audience is empty, and a campaign
        runs over an audience — so writing the leads is exactly what makes the
        first launch possible. Refusing the write meant the campaign could
        never be launched, and the refusal told the rep to go and launch it.

        Nothing sends in the meantime; the reference says so.
        """
        ref = await build(Fake(status="READY")).enrol(lead_id="lead-77", lgm_campaign_id=CAMPAIGN)
        assert ref == f"{CAMPAIGN}:lead-77:awaiting_launch"

    async def test_an_archived_campaign_is_still_refused(self):
        """Nothing makes an archived campaign send, so the write is pointless."""
        with pytest.raises(LgmError, match="archived"):
            await build(Fake(status="ARCHIVED")).enrol(lead_id="lead-77", lgm_campaign_id=CAMPAIGN)

    async def test_stopping_a_paused_campaign_does_nothing(self):
        fake = Fake(status="PAUSED")
        await build(fake).stop_campaign(CAMPAIGN)
        assert [r.method for r in fake.seen] == ["GET"], "LGM 400s on pausing a paused campaign"

    async def test_stopping_a_running_campaign_posts_the_pause(self):
        fake = Fake(status="RUNNING")
        await build(fake).stop_campaign(CAMPAIGN)
        assert body_of(fake.seen[-1]) == {"status": "PAUSED"}


class TestFailuresSayNothingTheyShouldNot:
    async def test_a_rejected_key_is_named_without_echoing_the_body(self):
        def refuse(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "invalid key secret-key for user x@y.com"})

        adapter = LiveLgmAdapter("secret-key", client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
        with pytest.raises(LgmError) as caught:
            await adapter.members()
        assert "rejected the API key" in str(caught.value)
        assert "secret-key" not in str(caught.value) and "x@y.com" not in str(caught.value)

    async def test_an_unreachable_provider_is_one_failure_mode(self):
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        adapter = LiveLgmAdapter("k", client=httpx.AsyncClient(transport=httpx.MockTransport(boom)))
        with pytest.raises(LgmError, match="could not be reached"):
            await adapter.members()


def shape(**over):
    """A registered shape, as the database holds one."""
    base = dict(
        key="standard_6_15", lgm_campaign_id=CAMPAIGN, touch_count=2,
        attribute_map={"1": "custom_attribute_1", "2": "custom_attribute_2"},
        subject_attribute_map={},
        step_channels={"1": "email", "2": "linkedin"},
        slot_labels={},
        lgm_audience_name="Gen360 · Standard",
    )
    return type("Shape", (), {**base, **over})


def step(
    order: int,
    attribute: str | None,
    active: bool = True,
    *,
    subject: str | None = None,
    channel: str | None = None,
) -> dict:
    """One step's templates, as LGM returns them.

    `channel` defaults to email for the first step and LinkedIn after, which is
    the shape of every cadence in the account this was written against — pass
    it explicitly where the test is about channels.
    """
    body = f"Hi {{{{customAttribute{attribute}}}}}" if attribute else "Hi there"
    subject_html = f"Re {{{{customAttribute{subject}}}}}" if subject else ""
    return {
        "order": order,
        "contentHtml": body,
        "subjectHtml": subject_html,
        "channel": channel or ("GOOGLE" if order == 0 else "LINKEDIN"),
        "active": active,
    }


class TestCheckingARegistrationAgainstTheLiveCampaign:
    async def test_a_matching_campaign_is_sound(self):
        fake = Fake(steps=(step(0, "1"), step(1, "2")))
        check = await check_shape(build(fake), shape())
        assert check.sound and check.steps == 2
        assert check.status == "active" and check.audience_name == "Gen360 · Standard"

    async def test_a_moved_slot_is_a_change_to_adopt_not_a_fault(self):
        """The check re-reads the templates, so it is the better authority.

        This used to be a finding, which left the stored map wrong and the only
        cure delete-and-re-register — refused once a campaign used the shape.
        Verification adopts it instead; a shape anything has *drafted* against
        still withholds its verification, which is asserted at the route.
        """
        fake = Fake(steps=(step(0, "1"), step(1, "7")))
        check = await check_shape(build(fake), shape())
        assert check.sound, "a slot moving is not, by itself, something broken"
        assert check.body_by_step == {1: "custom_attribute_1", 2: "custom_attribute_7"}
        assert any(
            "step 2's body moved from custom_attribute_2 to custom_attribute_7" in c
            for c in check.changes
        )

    async def test_a_subject_slot_is_read_apart_from_the_body(self):
        """They are separate templates in LGM, and only a subject template
        naming an attribute can carry a subject line of ours."""
        fake = Fake(steps=(step(0, "3", subject="2"), step(1, "1")))
        check = await check_shape(build(fake), shape())
        assert check.body_by_step == {1: "custom_attribute_3", 2: "custom_attribute_1"}
        assert check.subject_by_step == {1: "custom_attribute_2"}
        assert check.channel_by_step == {1: "email", 2: "linkedin"}

    async def test_a_slot_is_named_for_what_it_carries(self):
        """LGM lets these be named in its own interface and publishes the names
        nowhere, so they are derived from the step that uses them."""
        from app.services.lgm_client import derive_labels

        fake = Fake(steps=(step(0, "3", subject="2"), step(1, "1")))
        check = await check_shape(build(fake), shape())
        assert derive_labels(check) == {
            "custom_attribute_3": "email 1 body",
            "custom_attribute_2": "email 1 subject",
            "custom_attribute_1": "linkedin 2 body",
        }

    async def test_a_step_reading_no_attribute_would_send_nothing_of_ours(self):
        fake = Fake(steps=(step(0, "1"), step(1, None)))
        check = await check_shape(build(fake), shape())
        assert any("reads no lead attribute" in f for f in check.findings)

    async def test_a_changed_step_count_is_a_finding(self):
        fake = Fake(steps=(step(0, "1"),))
        check = await check_shape(build(fake), shape())
        assert any("1 active steps" in f for f in check.findings)

    async def test_a_campaign_retargeted_at_another_audience_is_a_finding(self):
        fake = Fake(steps=(step(0, "1"), step(1, "2")), audience=("aud-9", "Somebody else's list"))
        check = await check_shape(build(fake), shape())
        assert any("runs over audience" in f for f in check.findings)

    async def test_a_campaign_nobody_launched_is_reported_but_is_not_a_finding(self):
        """It used to be a finding. That made it impossible to launch anything.

        Unsound withholds `verified_at`; unverified blocks enrolment; an empty
        campaign cannot be launched — so a campaign waiting for its first
        launch could never leave that state. The status is still reported, and
        enrolment says plainly that nothing sends until somebody launches it.
        """
        fake = Fake(status="READY", steps=(step(0, "1"), step(1, "2")))
        check = await check_shape(build(fake), shape())
        assert check.status == "ready"
        assert not any("is ready" in f for f in check.findings)
