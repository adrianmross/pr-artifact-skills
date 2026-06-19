#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

SCREENSHOT="$WORK_DIR/screenshot.png"
OUT_DIR="$WORK_DIR/out"

python3 - "$SCREENSHOT" <<'PY'
import base64
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_bytes(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
))
PY

printf '$ pr-add-screenshot --visibility public --backend s3\n\n'

PYTHONPATH="$ROOT/lib/python/pr_artifacts" \
python3 "$ROOT/lib/python/pr_artifacts/publish_pr_artifact.py" \
  --repo adrianmross/example-app \
  --pr 42 \
  --file "$SCREENSHOT" \
  --label "Login screenshot" \
  --artifact-type screenshot \
  --visibility public \
  --backend s3 \
  --bucket pr-artifacts \
  --region us-east-1 \
  --endpoint-url https://minio.example.com \
  --public-base-url https://artifacts.example.com \
  --prefix screenshots \
  --timestamp 20260619T120000Z \
  --out-dir "$OUT_DIR" \
  --dry-run > "$WORK_DIR/result.json"

python3 - "$WORK_DIR/result.json" <<'PY'
import json
import pathlib
import sys

def trim(value, limit=76):
    return value if len(value) <= limit else value[: limit - 3] + "..."

result = json.loads(pathlib.Path(sys.argv[1]).read_text())
print("artifact uploaded: dry-run")
print(f"visibility:        {result['visibility']}")
print(f"backend:           {result['backend']}")
print(f"object key:        {trim(result['objectKey'])}")
print(f"url:               {trim(result['displayUrl'])}")
print(f"sha256:            {result['sha256'][:16]}...")
PY

printf '\nPR comment preview:\n'
python3 - "$OUT_DIR/comment.md" <<'PY'
import pathlib
import sys

for line in pathlib.Path(sys.argv[1]).read_text().splitlines()[:12]:
    print(line if len(line) <= 96 else line[:93] + "...")
PY
