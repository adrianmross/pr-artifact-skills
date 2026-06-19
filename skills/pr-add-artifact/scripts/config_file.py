"""Small config-file loader for PR artifact publishing."""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any


CONFIG_FILENAMES = (".pr-artifacts.yaml", ".pr-artifacts.yml", ".pr-artifacts.json")


def find_config(start: pathlib.Path | None = None) -> pathlib.Path | None:
    current = (start or pathlib.Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in [current, *current.parents]:
        for name in CONFIG_FILENAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def load_config(path: str = "", profile: str = "") -> dict[str, Any]:
    config_path = pathlib.Path(path).expanduser() if path else find_config()
    if config_path is None:
        return {}
    data = parse_config(config_path)
    profiles = data.get("profiles")
    if profile and isinstance(profiles, dict):
        selected = profiles.get(profile)
        if selected is None:
            raise ValueError(f"profile `{profile}` not found in {config_path}")
        merged = deep_merge({key: value for key, value in data.items() if key != "profiles"}, selected)
        merged["_configPath"] = str(config_path)
        merged["_profile"] = profile
        return merged
    data["_configPath"] = str(config_path)
    return data


def parse_config(path: pathlib.Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        payload = json.loads(text)
    else:
        payload = parse_simple_yaml(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a mapping")
    return payload


def parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            raise ValueError("simple YAML parser requires two-space indentation")
        key, sep, value = line.strip().partition(":")
        if not sep or not key:
            raise ValueError(f"unsupported YAML line: {raw_line}")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip() == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(value.strip())

    return root


def parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return os.path.expandvars(value)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def config_value(config: dict[str, Any], attr: str) -> Any:
    aliases = {attr, attr.replace("_", "-")}
    storage = config.get("storage")
    defaults = config.get("defaults")
    for section in (storage, defaults, config):
        if isinstance(section, dict):
            for alias in aliases:
                if alias in section:
                    return section[alias]
    return None


def config_secret(config: dict[str, Any], attr: str) -> str:
    env_key = config_value(config, f"{attr}_env")
    if env_key:
        return os.environ.get(str(env_key), "")
    value = config_value(config, attr)
    return "" if value is None else str(value)
