"""LLM hybrid matching: dictionary finds candidates, Claude judges them.

The dictionary (high recall, no name-block list) surfaces every company-name
candidate; cashtags ($AAPL) are explicit and auto-confirmed. Only the ambiguous
NAME candidates are sent to Claude, which decides in context whether each post
genuinely refers to the company (vs. a person, place, common word, or political
term). This replaces the hand-maintained name-block list with contextual judgment.
"""
from __future__ import annotations

from collections import Counter

from pydantic import BaseModel

from companies import Company
from match import build_index, dedupe_posts, excerpt_of, match_candidates

MODEL = "claude-opus-4-8"
BATCH = 40  # candidates per LLM call, to bound output size

SYSTEM = (
    "You decide whether a social-media post genuinely refers to a specific public "
    "company (its business, products, stock, or leadership), or whether the matched "
    "word is being used in an unrelated sense.\n\n"
    "A candidate is a (company, post) pair where the company's name appeared as a "
    "word in the post. Many are false matches: the word is a person's surname "
    "(e.g. 'Waters' = Maxine Waters, not Waters Corp; 'Rollins' = Brooke Rollins), a "
    "place or direction ('Southern' border, not Southern Company), a government or "
    "generic term ('intel' = intelligence, not Intel; 'target' = a goal/target, not "
    "Target; 'visa' = immigration, not Visa Inc.; 'progressive' = politics), or a "
    "plain English word.\n\n"
    "Return is_company=true ONLY when the post is actually about that company. When "
    "the word is used in another sense, return false. A brief, specific media outlet "
    "reference (e.g. 'Fox News') counts as referring to the company. Judge each item "
    "independently."
)


class Verdict(BaseModel):
    index: int
    is_company: bool
    reason: str


class Verdicts(BaseModel):
    verdicts: list[Verdict]


def _format_items(cands: list[dict]) -> str:
    lines = []
    for c in cands:
        lines.append(
            f'Item {c["id"]}: company "{c["company"]}" (ticker {c["ticker"]}). '
            f'Post: "{c["text"]}"'
        )
    return "\n\n".join(lines)


def _llm_adjudicate(cands: list[dict], *, client=None, model: str = MODEL) -> dict[int, bool]:
    """Call Claude to judge candidates. Returns {id: is_company}."""
    import anthropic

    client = client or anthropic.Anthropic()
    out: dict[int, bool] = {}
    for start in range(0, len(cands), BATCH):
        chunk = cands[start:start + BATCH]
        prompt = (
            "Judge each item below. Return a verdict for every item by its index.\n\n"
            + _format_items(chunk)
        )
        resp = client.messages.parse(
            model=model,
            max_tokens=4096,
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_format=Verdicts,
        )
        for v in resp.parsed_output.verdicts:
            out[v.index] = v.is_company
    return out


def count_with_llm(
    posts: list[dict], companies: list[Company], *, adjudicator=None, client=None,
    model: str = MODEL,
) -> tuple[Counter, dict[str, list[dict]], object]:
    """Hybrid count. `adjudicator` (cands -> {id: bool}) is injectable for tests;
    defaults to the real Claude call. Returns counts, refs, and the index."""
    index = build_index(companies, apply_name_stoplist=False)
    posts = dedupe_posts(posts)
    adjudicator = adjudicator or (lambda c: _llm_adjudicate(c, client=client, model=model))

    # Auto-confirm cashtags; queue name candidates for the LLM.
    post_confirmed: list[set[str]] = []
    cands: list[dict] = []
    for p in posts:
        text = p.get("text") or ""
        cashtags, names = match_candidates(text, index)
        confirmed = set(cashtags)
        for canon in names:
            if canon in cashtags:
                continue
            cands.append({
                "id": len(cands), "pi": len(post_confirmed), "canon": canon,
                "company": index.by_symbol[canon].name, "ticker": canon, "text": text,
            })
        post_confirmed.append(confirmed)

    verdicts = adjudicator(cands) if cands else {}
    for c in cands:
        if verdicts.get(c["id"]):
            post_confirmed[c["pi"]].add(c["canon"])

    counts: Counter = Counter()
    refs: dict[str, list[dict]] = {}
    for p, confirmed in zip(posts, post_confirmed):
        excerpt = excerpt_of(p.get("text") or "")
        for canon in confirmed:
            counts[canon] += 1
            refs.setdefault(canon, []).append({
                "url": p.get("url"),
                "created_at": p.get("created_at"),
                "excerpt": excerpt,
            })
    return counts, refs, index
