#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VALIDATOR="${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/validate_plugin.py"
PYTHON_BIN="${PYTHON:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    PYTHON_BIN="python"
  fi
fi

if [[ -f "$VALIDATOR" ]]; then
  "$PYTHON_BIN" "$VALIDATOR" "$ROOT"
  exit 0
fi

"$PYTHON_BIN" - "$ROOT" <<'PY'
import json
import pathlib
import sys

import yaml

root = pathlib.Path(sys.argv[1])
manifest_path = root / ".codex-plugin" / "plugin.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

required_manifest = ["name", "version", "description", "author", "skills", "interface"]
missing = [field for field in required_manifest if field not in manifest]
if missing:
    raise SystemExit(f"plugin.json missing fields: {', '.join(missing)}")
if manifest["skills"].rstrip("/") not in {".", "./skills", "skills"}:
    raise SystemExit("plugin.json field `skills` must point at ./skills/")

interface = manifest.get("interface")
if not isinstance(interface, dict):
    raise SystemExit("plugin.json field `interface` must be an object")
for field in ["displayName", "shortDescription", "longDescription", "developerName", "category"]:
    if not isinstance(interface.get(field), str) or not interface[field].strip():
        raise SystemExit(f"plugin.json interface.{field} must be non-empty")

skills_root = root / "skills"
for skill_md in sorted(skills_root.glob("*/SKILL.md")):
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SystemExit(f"{skill_md} must start with YAML frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise SystemExit(f"{skill_md} frontmatter is not closed")
    frontmatter = yaml.safe_load(text[4:end])
    if not isinstance(frontmatter, dict):
        raise SystemExit(f"{skill_md} frontmatter must be an object")
    for field in ["name", "description"]:
        if not isinstance(frontmatter.get(field), str) or not frontmatter[field].strip():
            raise SystemExit(f"{skill_md} frontmatter field `{field}` must be non-empty")

    agent_yaml = skill_md.parent / "agents" / "openai.yaml"
    if agent_yaml.exists():
        payload = yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("interface"), dict):
            raise SystemExit(f"{agent_yaml} must contain interface metadata")

print(f"Plugin fallback validation passed: {root}")
PY
