"""Web search on Gemini, and refusing an answer that cannot show it searched.

Every case here was seen on the live API before it was written down:

* With a response schema, Gemini returns no grounding metadata at all. The
  only proof a page came from a search is a `grounding-api-redirect` link.
* At a low thinking level it did not search, and produced plausible passages
  from memory with a prompt token count equal to what was sent.
* Quoting a well-covered company verbatim was refused as `RECITATION`.

No network: the transport, the token count and the redirect lookups are all
stubbed, so these check our decisions rather than Google's.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from app.schemas.draft import FreshnessVerdict
from app.schemas.evidence import EvidenceBatch
from app.services import gemini
from app.services import gemini_grounding as grounding
from app.services.prompt import PromptAssembly, SystemBlock
from app.services.stages import WEB_TOOLS

R1 = grounding.REDIRECT_PREFIX + "AUZIYQE-one"
R2 = grounding.REDIRECT_PREFIX + "AUZIYQG-two"
REAL = {R1: "https://stripe.com/newsroom/news/series-i"}


def passage(url: str, excerpt: str = "Stripe raised a Series I.") -> dict:
    return {"source_type": "news", "source_url": url, "excerpt": excerpt}


def batch(*urls: str, not_found=()) -> EvidenceBatch:
    return EvidenceBatch.model_validate(
        {"evidence": [passage(u, f"fact {i}") for i, u in enumerate(urls)],
         "not_found": list(not_found)}
    )


async def resolver(links):
    return {link: REAL.get(link) for link in links}


def counter(value: int, calls: list | None = None):
    async def count():
        if calls is not None:
            calls.append(1)
        return value
    return count


class TestTheToolsSent:
    def test_web_search_becomes_google_search_and_fetch_is_dropped(self):
        """URL context reports nothing checkable under a schema, so a page it
        "read" would be unverifiable — search reaches the same pages as links."""
        assert grounding.translate_tools(WEB_TOOLS) == [{"googleSearch": {}}]

    def test_a_tool_with_no_equivalent_is_refused_not_dropped(self):
        with pytest.raises(grounding.GroundingError, match="code_execution"):
            grounding.translate_tools([{"type": "code_execution_20250825"}])

    def test_a_web_stage_asks_for_result_links_and_short_quotes(self):
        body = gemini.build_request(
            model="gemini-3.5-flash-lite",
            prefix=PromptAssembly(blocks=[SystemBlock("stage", "research")], tools=WEB_TOOLS),
            user_content="the account",
            output_model=EvidenceBatch,
            effort="high",
            max_tokens=8000,
        )
        assert body["tools"] == [{"googleSearch": {}}]
        parts = body["systemInstruction"]["parts"]
        assert parts[0]["text"] == "research", "the shared prefix is untouched"
        assert "Google Search result" in parts[-1]["text"]
        assert "under 30 words" in parts[-1]["text"]

    def test_a_stage_without_tools_is_sent_without_them(self):
        body = gemini.build_request(
            model="gemini-3.5-flash-lite",
            prefix=PromptAssembly(blocks=[SystemBlock("stage", "x")]),
            user_content="u",
            output_model=FreshnessVerdict,
            effort="low",
            max_tokens=1000,
        )
        assert "tools" not in body
        assert len(body["systemInstruction"]["parts"]) == 1


class TestAnAnswerMustShowItSearched:
    async def test_no_links_and_no_injected_results_is_refused(self):
        """Seen live at thinking level low: 121 tokens billed for 122 sent."""
        with pytest.raises(grounding.GroundingError, match="without searching"):
            await grounding.ground(
                batch(not_found=["funding"]),
                prompt_tokens=121, count_request_tokens=counter(122), resolve=resolver,
            )

    async def test_the_refusal_says_what_to_change(self):
        with pytest.raises(grounding.GroundingError, match="Model config"):
            await grounding.ground(
                batch(not_found=["funding"]),
                prompt_tokens=130, count_request_tokens=counter(125), resolve=resolver,
            )

    async def test_an_honest_empty_answer_after_a_search_is_kept(self):
        """Seen live: an obscure company, 704 tokens billed for 125 sent, and
        `not_found` naming what was searched. That is a finding."""
        out = await grounding.ground(
            batch(not_found=["Apex funding rounds"]),
            prompt_tokens=704, count_request_tokens=counter(125), resolve=resolver,
        )
        assert out.evidence == []
        assert out.not_found == ["Apex funding rounds"]

    async def test_a_link_is_proof_enough_and_saves_the_count(self):
        calls: list = []
        await grounding.ground(
            batch(R1), prompt_tokens=10,
            count_request_tokens=counter(0, calls), resolve=resolver,
        )
        assert calls == [], "counted tokens for an answer a link already proved"


class TestEvidenceKeepsOnlyWhatWasRetrieved:
    async def test_a_result_link_is_swapped_for_the_page_it_leads_to(self):
        """The page re-opens; the grounding link changes every call and would
        defeat the dedup hash."""
        out = await grounding.ground(
            batch(R1), prompt_tokens=900, count_request_tokens=counter(100), resolve=resolver,
        )
        assert [e.source_url for e in out.evidence] == [REAL[R1]]

    async def test_a_link_the_model_wrote_itself_is_discarded_and_said_to_be(self):
        """Seen live: tidy newsroom URLs, written from memory."""
        out = await grounding.ground(
            batch(R1, "https://stripe.com/newsroom/news/annual-letter-2025"),
            prompt_tokens=900, count_request_tokens=counter(100), resolve=resolver,
        )
        assert [e.source_url for e in out.evidence] == [REAL[R1]]
        assert any("1 passage(s) discarded" in n for n in out.not_found)

    async def test_a_result_link_that_no_longer_resolves_is_discarded(self):
        out = await grounding.ground(
            batch(R1, R2), prompt_tokens=900, count_request_tokens=counter(100), resolve=resolver,
        )
        assert len(out.evidence) == 1
        assert any("discarded" in n for n in out.not_found)

    async def test_discarding_everything_still_leaves_a_valid_batch(self):
        """An empty batch must say what happened, or the contract rejects it."""
        out = await grounding.ground(
            batch("https://example.com/made-up"),
            prompt_tokens=900, count_request_tokens=counter(100), resolve=resolver,
        )
        assert out.evidence == []
        assert out.not_found and "discarded" in out.not_found[0]


class TestAPassageAboutAPerson:
    async def test_it_keeps_who_it_is_about_and_points_at_the_page(self):
        """Contact research runs through the same filter: a link that did not
        come from a search is discarded, and a kept one keeps its person."""
        from app.schemas.evidence import ContactEvidenceBatch

        found = ContactEvidenceBatch.model_validate(
            {
                "evidence": [
                    {**passage(R1), "contact_id": "c-1"},
                    {**passage("https://example.com/made-up", "invented"), "contact_id": "c-1"},
                ],
                "searched_for": [{"contact_id": "c-1", "searched": ["role change"]}],
            }
        )
        out = await grounding.ground(
            found, prompt_tokens=900, count_request_tokens=counter(100), resolve=resolver,
        )
        assert [(e.contact_id, e.source_url) for e in out.evidence] == [("c-1", REAL[R1])]
        assert any("discarded" in n for n in out.not_found)


class TestOtherContractsKeepTheirShape:
    async def test_links_elsewhere_are_pointed_at_their_pages(self):
        class Person(BaseModel):
            name: str
            found_at: str

        out = await grounding.ground(
            Person(name="Priya", found_at=R1),
            prompt_tokens=900, count_request_tokens=counter(100), resolve=resolver,
        )
        assert out.found_at == REAL[R1]


class TestTheResolver:
    async def test_only_a_redirect_to_a_real_page_counts(self):
        class Response:
            def __init__(self, status, location):
                self.status_code = status
                self.headers = {"location": location} if location else {}

        answers = {
            R1: Response(302, "https://stripe.com/a"),
            R2: Response(200, None),
        }
        seen_kwargs: list[dict] = []

        class Client:
            async def get(self, url, **kwargs):
                seen_kwargs.append(kwargs)
                return answers[url]

        out = await grounding.resolve_links({R1, R2}, Client())
        assert out == {R1: "https://stripe.com/a", R2: None}
        assert all(k["follow_redirects"] is False for k in seen_kwargs), "the page itself is never fetched"


# ------------------------------------------------------------------ the call
class _NoClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _payload(text: str | None, finish: str = "STOP", prompt: int = 900) -> dict:
    parts = [{"text": text}] if text is not None else []
    return {
        "candidates": [{"finishReason": finish, "content": {"parts": parts}}],
        "usageMetadata": {"promptTokenCount": prompt, "candidatesTokenCount": 20},
    }


@pytest.fixture
def wire(monkeypatch):
    """A fake Gemini: queued responses in, request bodies recorded."""
    sent: list[dict] = []
    queue: list[dict] = []
    counted: list[int] = []

    async def post(client, *, model, api_key, body):
        sent.append(body)
        return queue.pop(0)

    async def count(client, *, model, api_key, body):
        counted.append(1)
        return 120

    async def resolve(links, client):
        return {link: REAL.get(link) for link in links}

    monkeypatch.setattr(gemini, "_client", lambda *a, **k: _NoClient())
    monkeypatch.setattr(gemini, "_post", post)
    monkeypatch.setattr(gemini, "_count_tokens", count)
    monkeypatch.setattr(grounding, "resolve_links", resolve)
    return sent, queue, counted


def _call(output_model, tools=True):
    return gemini.call(
        model="gemini-3.5-flash-lite",
        api_key="k",
        prefix=PromptAssembly(
            blocks=[SystemBlock("stage", "research")],
            tools=WEB_TOOLS if tools else [],
        ),
        user_content="the account",
        output_model=output_model,
        effort="high",
        max_tokens=8000,
    )


class TestTheCall:
    async def test_a_recitation_refusal_is_retried_once_with_shorter_quotes(self, wire):
        sent, queue, _ = wire
        queue += [_payload(None, "RECITATION"), _payload(json.dumps({"evidence": [passage(R1)]}))]

        parsed, usage = await _call(EvidenceBatch)

        assert [e.source_url for e in parsed.evidence] == [REAL[R1]]
        assert len(sent) == 2
        retried = sent[1]["contents"][0]["parts"][0]["text"]
        assert grounding.RECITATION_RETRY_NOTE in retried
        assert usage["input_tokens"] == 1800, "the refused call is billed too"

    async def test_a_second_recitation_is_final(self, wire):
        _, queue, _ = wire
        queue += [_payload(None, "RECITATION"), _payload(None, "RECITATION")]
        with pytest.raises(gemini.GeminiRefusedError):
            await _call(EvidenceBatch)

    async def test_an_answer_from_memory_is_refused(self, wire):
        _, queue, counted = wire
        queue.append(_payload(json.dumps({"evidence": [], "not_found": ["funding"]}), prompt=121))
        with pytest.raises(gemini.GeminiError, match="without searching"):
            await _call(EvidenceBatch)
        assert counted == [1]

    async def test_a_stage_without_tools_is_not_grounded(self, wire):
        _, queue, counted = wire
        queue.append(_payload('{"proceed": true}', prompt=50))
        parsed, _ = await _call(FreshnessVerdict, tools=False)
        assert parsed.proceed is True
        assert counted == [], "a stage that never asked to search was checked for one"
