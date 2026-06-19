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

if [[ -f "$VALIDATOR" ]] && "$PYTHON_BIN" -c 'import yaml' >/dev/null 2>&1; then
  "$PYTHON_BIN" "$VALIDATOR" "$ROOT"
  exit 0
fi

"$PYTHON_BIN" - "$ROOT" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest_path = root / ".codex-plugin" / "plugin.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))


def parse_frontmatter(text):
    result = {}
    current_key = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith(" ") and current_key:
            result[current_key] = f"{result[current_key]} {raw_line.strip()}".strip()
            continue
        key, sep, value = raw_line.partition(":")
        if not sep:
            continue
        current_key = key.strip()
        result[current_key] = value.strip().strip('"').strip("'")
    return result


def parse_nested_keys(text):
    keys = set()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        key, sep, _ = line.strip().partition(":")
        if sep:
            keys.add(key)
    return keys

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
    frontmatter = parse_frontmatter(text[4:end])
    for field in ["name", "description"]:
        if not isinstance(frontmatter.get(field), str) or not frontmatter[field].strip():
            raise SystemExit(f"{skill_md} frontmatter field `{field}` must be non-empty")

    agent_yaml = skill_md.parent / "agents" / "openai.yaml"
    if agent_yaml.exists():
        payload = parse_nested_keys(agent_yaml.read_text(encoding="utf-8"))
        if "interface" not in payload:
            raise SystemExit(f"{agent_yaml} must contain interface metadata")

print(f"Plugin fallback validation passed: {root}")
PY
