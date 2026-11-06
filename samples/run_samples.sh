#!/usr/bin/env bash
# SIRAJ · samples/run_samples.sh — upload each sample through the running API
# and print the report.
#
#   ./samples/run_samples.sh                 # against http://localhost:8000
#   BASE_URL=http://host:8000 ./samples/run_samples.sh
#
# The samples are uploaded in dependency order: places create the parent codes
# that persons reference, sources create the primary-source codes, and the
# bilingual persons file re-imports the same records through upsert.  Every
# sample goes through the documented three calls — preview → validate → commit.
set -u
BASE_URL="${BASE_URL:-http://localhost:8000}"
HERE="$(cd "$(dirname "$0")" && pwd)"
FAILED=0

say() { printf '%s\n' "$*"; }

report() {  # report <label> <json>
  python3 - "$1" <<'PY'
import json, sys
label = sys.argv[1]
try:
    doc = json.load(sys.stdin)
except Exception:
    print(f"  {label:<34} ! response is not JSON"); sys.exit(1)
r = doc.get("report") or doc
errs = r.get("errors") or []
print(f"  {label:<34} rows={r.get('total', 0)} created={r.get('created', 0)} "
      f"updated={r.get('updated', 0)} skipped={r.get('skipped', 0)} "
      f"failed={r.get('failed', 0)}")
for e in errs[:5]:
    print(f"      row {e.get('row')} · {e.get('field')}: {e.get('message')}")
sys.exit(1 if r.get("failed") else 0)
PY
}

upload() {  # upload <entity> <file> <mode>
  local entity="$1" file="$2" mode="$3"
  local name; name="$(basename "$file")"
  local preview
  preview="$(curl -sf -F "entity=$entity" -F "file=@$file" "$BASE_URL/api/import/preview")" || {
    say "  $name — preview failed"; FAILED=1; return; }
  local upload_id mapping
  upload_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("upload_id",""))' <<<"$preview")"
  mapping="$(python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("mapping") or {}))' <<<"$preview")"
  if [ -z "$upload_id" ]; then say "  $name — no upload_id in preview"; FAILED=1; return; fi

  local payload
  payload="$(python3 - "$entity" "$upload_id" "$mapping" "$mode" <<'PY'
import json, sys
print(json.dumps({"entity": sys.argv[1], "upload_id": sys.argv[2],
                  "mapping": json.loads(sys.argv[3]), "mode": sys.argv[4]}))
PY
)"
  curl -sf -X POST "$BASE_URL/api/import/validate" \
       -H 'Content-Type: application/json' -d "$payload" >/dev/null || {
    say "  $name — validate failed"; FAILED=1; return; }
  local out
  out="$(curl -sf -X POST "$BASE_URL/api/import/commit" \
        -H 'Content-Type: application/json' -d "$payload")" || {
    say "  $name — commit failed"; FAILED=1; return; }
  report "$name" <<<"$out" || FAILED=1
}

say "SIRAJ · sample import against $BASE_URL"
upload place     "$HERE/places-import.csv"              create
upload source    "$HERE/sources-import.json"            create
upload person    "$HERE/persons-import.csv"             create
upload person    "$HERE/persons-import-bilingual.csv"   upsert

say ""
if [ "$FAILED" -eq 0 ]; then say "OK — every sample imported"; else say "FAILURES — see above"; fi
exit "$FAILED"
