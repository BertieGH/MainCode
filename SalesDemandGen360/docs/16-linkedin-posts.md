# 16 · Indexed LinkedIn posts — ranking, and the activity rating that is not free

What `linkedin_index` reads, what is worth keeping, and what the owner asked for that the
measurements refused. Written 2026-10-08, after §102's five-account run.

`linkedin_index` is the most productive source on this book by a wide margin: **88 of 145 passages,
61%**, hitting five of five accounts. So it is worth getting right.

---

## What the posts query actually returns

**Not employee activity.** `site:linkedin.com/posts "{company}"` is a *mentions* query — it returns
whoever is talking about the company.

Measured across seven accounts with stored posts: **45 distinct post authors, of whom exactly 1 is
an employee** — cross-matched against the `/in/` profiles the same source returns, which *are*
employees, nine or ten per company. The rest are trade media and analysts: `battery-industry`,
`dxtoday-podcast`, `hk-business-wire`, `business-news-today-reporter`, `ieefa-asia-pacific`, plus
named figures like `jigarshahdc` and `kurt-kelty` who work elsewhere.

| account | post authors | employees | outside |
|---|---|---|---|
| KORE Power | 10 | 0 | 10 |
| KULR | 9 | 0 | 9 |
| WeaveGrid | 9 | 1 | 8 |
| Bollinger | 8 | 0 | 8 |
| Free Fly | 6 | 0 | 6 |
| Anuschka | 2 | 0 | 2 |

So these passages are **third-party coverage**, closer to `trade_press` than to anything the company
says about itself. They are stored at `reliability = 0.6` for that reason — below `company_site`'s
first-hand 0.85, because a podcast host's account of a launch is not the launch being announced.

Posts are **100% dated**: 49 of 49 decoded a date from the activity id. That matters more than it
sounds, because §102 measured that signals track the *dated* count, not the raw count.

---

## What this means for a contact activity rating

The owner asked for a per-contact LinkedIn activity rating, to weight outreach toward people who
post. The measurement above says **the company query cannot provide it**. Rating a person needs
`site:linkedin.com/posts "{person name}"` — one SERP credit per contact.

At 1,000–5,000 outreach a month that is 1,000–5,000 credits for the rating alone. What makes it
affordable at all is the existing company gate: 8 companies in 10 have no post inside 90 days, so
most contacts would never be queried. Even so it is a per-head cost, and it is **not built**.

If it is built later, two things are already settled:

* **The slug fix is a prerequisite**, and is done. Apollo stores `/in/apoorv-bhargava-94100842`;
  his own post is at `/posts/apoorv-bhargava`. Compared exactly those are two people — and the first
  measurement of authorship reported *zero* employees among forty-five for precisely this reason, a
  number produced by the mismatch rather than by the data. `linkedin.same_slug` strips a trailing
  `-[0-9a-f]{6,}` from both sides, and only from five characters up, so a genuine namesake tail is
  not treated as an id.
* **`unknown` must not read as `quiet`.** Never queried, and queried-and-silent, are different
  facts. Deprioritising somebody for a measurement that never happened is the error the coverage
  work keeps correcting.

**Neither Apollo nor LGM has it.** Checked against the live account. Apollo's `last_activity_date`
is its own sequence activity and is null here; `intent_strength` and `show_intent` are the Buying
Intent add-on, company-level and not subscribed; `linkedin_uid` is not even populated. LGM reports
only reactions to our own outreach — `LINKEDIN_MESSAGE_SENT`, `LINKEDIN_VISIT`, `CONNECT`, replies —
which exist only after contact and so cannot order who to contact.

---

## Ranking: what is built

`post_ranking`, applied in `linkedin_serp` **before anything is stored**. Evidence is immutable, so
a post stored is stored for good and a post dropped is never cited.

A page returns ten posts whatever is asked for, and four companies in six return a full ten — so the
question is which to keep, not how to get more.

**Scored lexically.** An LLM call to rank the inputs to an LLM is circular; an embedding needs
infrastructure this installation does not have, and a 200-character snippet is thin material for
one. A lexicon is free, deterministic, and can say *why* — "it named ERP and migration" is an answer
a rep can use, where a cosine distance is not.

**Three lexicons, two axes:**

* `TECHNOLOGY` — hand-written, broad, and deliberately free of vendor names.
* **fit** — derived from the active services' names, descriptions and positioning angles. That
  config is already maintained on the Services screen; a second hand-kept list is the one that goes
  stale, and an installation selling something else gets its own lexicon for free.
* **signals** — derived from the **active signal type keys and labels**. This is what stops the
  filter undoing extraction's work, and it was added because of a specific loss: scoring on
  technology and fit alone dropped "After three remarkable years at WeaveGrid, it's time to…", a
  departure that `leadership_change_executive` exists to catch and that names no technology.

Top three by technology, top three by fit, interleaved, capped at **six** — two threes rather than
one six, because a single ranking lets a long generic post outrank a short specific one.

### Three things measurement forced

**1 · Prefix matching from five characters.** With whole-word matching throughout, `join` did not
match "She **joined** Bollinger Innovations as its first…" and `acquire` did not match
"acquisition". Terms of five characters or more now match their inflections; shorter ones stay
whole, because prefixing `ai` would match "aid" and "air" and every post would score. Short
irregulars (`joined`, `joins`) get their own entry. Event words arrived the same way — `delist`,
`axed`, `closure`, `layoff` — because "confirms Nasdaq delisting" and "axed a $1.25B Arizona battery
plant" both scored zero, and a plant closure is as much a trigger as a launch.

**2 · A stoplist on the derived fit lexicon.** Its first run produced `that`, `based`, `without`,
`team`, `build` and `ship` as fit terms. Each matches a large share of any prose, so the score would
have ranked every post alike while appearing to work.

**3 · Boilerplate by shape, not topic — and this is where the saving is.** `is_boilerplate` drops
LinkedIn's own chrome ("26,264 followers. Report this post") and brand lists ("ettitude Cozy Earth
BAM Clothing Thought Clothing") before scoring. A topic filter cannot do this job: measured, a
customer's fraud complaint scores on the same terms as a real leadership hire. A shape filter cannot
discard an event for being about an unexpected subject. The first version of the list rule also
demanded at most one full stop, which the brand lists defeated — a stored excerpt opens with
"Sep 23, 2026 ..." and that is three full stops before the list begins.

### The policy, and why it is not "drop what does not score"

Dropping every non-scorer measured as an **82% saving and a real loss**: "confirms Nasdaq delisting"
and "axed a $1.25B battery plant" both scored zero at the time. A lexicon cannot be trusted to
recognise every event worth citing.

So the lexicon decides the **order** and the cap decides the **volume**. Spare budget goes to the
most recent remaining posts, scored or not — the cap is the same either way, so the real choice is
between storing a recent unscored post and storing nothing. The coverage note says which are which,
"10 post(s) seen, 5 kept, 3 on recency alone", because a reader has to be able to tell "this
matched" from "there was room".

Measured on the stored corpus: **49 seen → 15 kept, 69% fewer passages**, with the acquisition, the
leadership hire and the hiring post all retained.

### Fetch wide, select narrow

`max_age_days` (365) governs the **fetch**. A SERP page returns ten results whatever window is asked
for, so narrowing the query buys no credits and only changes which ten arrive — on a company that
posts quarterly it wastes the call.

`PAYLOAD_DAYS` (90) governs **selection**, applied by the reader at payload time, not by the sweep.
The first implementation applied it during the sweep, which quietly undid the design: a stored post
outside the window was gone, so changing the window would have meant re-fetching, the one thing this
is meant to avoid. It is now free to change.

---

## Still open

* The per-contact activity rating, above — a credit a head, and the owner's call.
* Bollinger's customer fraud complaints survive ranking. They are arguably reputational signal and
  certainly not useful for an IT services pitch, and no shape rule separates them from a real post.
* `strategy` does not yet call `post_ranking.pick` with `PAYLOAD_DAYS`. The sweep-side cap is in;
  the read-side window is not.
