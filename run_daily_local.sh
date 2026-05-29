#!/bin/bash
# Daily local run: emit candidates -> adjudicate via headless Claude (no API key,
# uses your Claude subscription) -> finalize chart -> commit & push.
# Invoked by the launchd agent; safe to run by hand too.
set -uo pipefail

export PATH="/Users/jacewardell/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd /Users/jacewardell/Projects/Personal/trump-stock-cloud || exit 1

PY=./venv/bin/python
CLAUDE=/Users/jacewardell/.local/bin/claude
GIT=/opt/homebrew/bin/git

DATE=$($PY -c "from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d'))")
echo "===== $(date) | run for $DATE ====="

# 1. Emit candidates (fetch last 24h from the public archive)
$PY src/main.py --emit-candidates --date "$DATE" || { echo "emit failed"; exit 1; }

CAND="candidates/$DATE.json"
VERD="verdicts/$DATE.json"

# 2. Adjudicate name candidates with headless Claude (only if there are any)
NCANDS=$($PY -c "import json;d=json.load(open('$CAND'));print(sum(len(r['candidates']) for r in d['records']))")
echo "Name candidates to adjudicate: $NCANDS"
if [ "$NCANDS" -gt 0 ]; then
  "$CLAUDE" -p "Adjudicate today's company-name matches. Read the file $CAND. Each record has a post 'text' and 'candidates' (each {id, ticker, company}: a company NAME matched in the text). Follow the rules in RUNBOOK.md step 2: for each candidate id decide true if the post genuinely refers to THAT company, false if the matched word is used in another sense (surname, place, generic/political term, or only in a URL). Write $VERD as a flat JSON object mapping every candidate id (as a string) to true/false, e.g. {\"0\": true, \"1\": false}. Cover every id. Write only that file." \
    --permission-mode acceptEdits \
    --allowedTools "Read" "Write" "Glob" "Grep" \
    --add-dir . \
    || { echo "adjudication failed; using empty verdicts"; echo '{}' > "$VERD"; }
else
  echo '{}' > "$VERD"
fi

# 3. Finalize -> output/DATE.png + output/DATE.json (cashtags-only if verdicts missing)
$PY src/main.py --finalize --date "$DATE" || { echo "finalize failed"; exit 1; }

# 4. Commit + push the results
$GIT add output/ candidates/ verdicts/
if $GIT diff --cached --quiet; then
  echo "Nothing to commit"
else
  $GIT -c user.name="Jace Wardell" -c user.email="jace.wardell@flybreeze.com" \
    commit -q -m "Daily chart $DATE"
  if $GIT push -q origin main; then echo "Pushed"; else echo "Push FAILED"; fi
fi
echo "===== done ====="
