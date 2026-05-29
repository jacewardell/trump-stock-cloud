# Daily adjudication runbook (for the scheduled Claude Code job)

This is the routine a scheduled Claude Code agent runs each day. It needs **no
Anthropic API key** — Claude Code itself does the adjudication in step 2.

Run from the project root. Commands use `python3`; locally you can use
`./venv/bin/python` instead.

## Setup (cloud agent: do this first each run)

```
python3 -m pip install --quiet -r requirements.txt
```

(`anthropic` in requirements is unused by this runbook — emit/finalize only need
matplotlib, requests, and python-dotenv. Installing it is harmless.)

## Steps

1. **Emit candidates** (fetches the last 24h from the public archive):

   ```
   python3 src/main.py --emit-candidates
   ```

   This writes `candidates/<TODAY>.json` (TODAY = US/Eastern date). It prints the
   path and how many name candidates need judgment. If 0 candidates, skip to
   step 3 (still finalize so a chart is produced).

2. **Adjudicate.** Read `candidates/<TODAY>.json`. It contains `records`, one per
   post: `text`, `confirmed` (cashtag tickers — already counted, ignore), and
   `candidates` (each `{id, ticker, company}` — a company NAME matched in the
   post text). For each candidate, decide whether the post genuinely refers to
   **that company** (its business, products, stock, or leadership), vs. the word
   being used in another sense. Write `verdicts/<TODAY>.json` as a flat JSON
   object `{"<id>": true|false, ...}` covering every candidate id.

   **Return false when the matched word is:**
   - a person's surname — "Waters" = Maxine Waters (not Waters Corp); "Rollins"
     = Brooke Rollins; "McCormick" = a congressman (not McCormick & Co)
   - a place/direction — "Southern" border / district (not Southern Company)
   - a government/generic term — "intel" = intelligence (not Intel); "target" =
     a goal/military target (not Target); "visa" = immigration (not Visa Inc.);
     "progressive" = politics (not Progressive); "news" = the word (not News Corp)
   - a plain English word, or only present inside a URL (e.g. amazon.com link)

   **Return true when** the post is actually about the company. A brief media
   reference ("Fox", "FoxNews") counts as Fox Corp. "Intel Stock continues to
   rise" is Intel. A list naming executives with their firms ("Larry Culp (GE
   Aerospace)") confirms each named company. Judge each id independently.

3. **Finalize** (combines candidates + verdicts → bar chart + JSON):

   ```
   python3 src/main.py --finalize
   ```

   Output lands in `output/<TODAY>.png` and `output/<TODAY>.json`.

4. **Commit the results back** (so the chart history persists in the repo):

   ```
   git add output/ candidates/ verdicts/
   git commit -m "Daily chart <TODAY>"
   git push
   ```

   If `git push` fails for auth reasons, report it — the run still succeeded, but
   the platform needs write access to the repo for persistence.

## Notes
- Use today's US/Eastern date for all steps; `main.py` defaults to it, so don't
  pass `--date` unless backfilling a specific day.
- If `verdicts/<TODAY>.json` is missing at finalize time, only cashtag mentions
  are counted (a warning is printed) — so always complete step 2.
