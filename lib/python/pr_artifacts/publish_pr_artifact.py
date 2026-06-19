#!/usr/bin/env python3
"""Publish local artifacts to object storage and update a GitHub PR comment."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sys
import tarfile
import tempfile
import urllib.parse

try:
    from .config_file import config_secret, config_value, load_config
    from .object_store import (
        StorageConfig,
        config_from_args,
        content_type_for,
        presigned_get_url,
        public_url,
        result_json,
        run,
        sha256_file,
        storage_ref,
        upload_file,
    )
except ImportError:
    from config_file import config_secret, config_value, load_config
    from object_store import (
        StorageConfig,
        config_from_args,
        content_type_for,
        presigned_get_url,
        public_url,
        result_json,
        run,
        sha256_file,
        storage_ref,
        upload_file,
    )


SENSITIVE_TYPES = {"sbom", "provenance", "log", "coverage"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SENSITIVE_NAME_RE = re.compile(
    r"(^|[._/-])("
    r"\.env|\.npmrc|\.pypirc|\.netrc|"
    r"id_rsa|id_dsa|id_ecdsa|id_ed25519|"
    r"kubeconfig|dockerconfigjson|"
    r"secret|secrets|credential|credentials|password|passwd|token|private[-_]key"
    r")($|[._/-])",
    re.IGNORECASE,
)
SENSITIVE_CONTENT_RE = re.compile(
    r"(BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY|"
    r"AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|"
    r"(?i:password|passwd|token|api[_-]?key|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,})"
)


def slug(value: str, fallback: str = "artifact") -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-")
    return normalized or fallback


def stage_artifact(source: pathlib.Path, work_dir: pathlib.Path, label: str) -> pathlib.Path:
    if not source.exists():
        raise FileNotFoundError(source)

    if source.is_file():
        return source

    if source.is_dir():
        archive = work_dir / f"{slug(label)}.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            for entry in sorted(source.rglob("*")):
                if entry.is_file():
                    tar.add(entry, arcname=entry.relative_to(source))
        return archive

    raise ValueError(f"Unsupported artifact path: {source}")


def privacy_candidates(source: pathlib.Path) -> list[pathlib.Path]:
    if source.is_file():
        return [source]
    if source.is_dir():
        return [path for path in source.rglob("*") if path.is_file()]
    return []


def enforce_public_privacy(source: pathlib.Path, args: argparse.Namespace) -> None:
    if args.visibility != "public" or not args.privacy_checks or args.allow_sensitive_public:
        return
    if args.artifact_type in SENSITIVE_TYPES:
        raise ValueError(
            f"{args.artifact_type} defaults to private. Pass --allow-sensitive-public to publish it publicly."
        )
    matches = []
    for path in privacy_candidates(source):
        candidate = str(path.relative_to(source) if source.is_dir() else path.name)
        if SENSITIVE_NAME_RE.search(candidate):
            matches.append(candidate)
    if matches:
        preview = ", ".join(matches[:5])
        suffix = "" if len(matches) <= 5 else f", and {len(matches) - 5} more"
        raise ValueError(
            f"Refusing public upload because artifact path looks sensitive: {preview}{suffix}. "
            "Use --visibility private, --visibility signed, or pass --allow-sensitive-public intentionally."
        )
    content_matches = sensitive_content_matches(source)
    if content_matches:
        preview = ", ".join(content_matches[:5])
        suffix = "" if len(content_matches) <= 5 else f", and {len(content_matches) - 5} more"
        raise ValueError(
            f"Refusing public upload because artifact content looks sensitive: {preview}{suffix}. "
            "Use --visibility private, --visibility signed, or pass --allow-sensitive-public intentionally."
        )


def sensitive_content_matches(source: pathlib.Path) -> list[str]:
    matches = []
    for path in privacy_candidates(source)[:100]:
        try:
            sample = path.read_bytes()[:65536]
        except OSError:
            continue
        if b"\x00" in sample:
            continue
        text = sample.decode("utf-8", "ignore")
        if SENSITIVE_CONTENT_RE.search(text):
            matches.append(str(path.relative_to(source) if source.is_dir() else path.name))
    return matches


def enforce_max_size(artifact: pathlib.Path, max_bytes: int) -> None:
    if max_bytes <= 0:
        return
    size = artifact.stat().st_size
    if size > max_bytes:
        raise ValueError(f"Artifact is {size} bytes, exceeding --max-bytes {max_bytes}")


def build_object_key(prefix: str, repo: str, pr: str, label: str, artifact: pathlib.Path, timestamp: str) -> str:
    owner, _, name = repo.partition("/")
    return "/".join(
        part
        for part in [
            "/".join(slug(p) for p in prefix.split("/") if p),
            slug(owner or "owner"),
            slug(name or repo),
            f"pr-{slug(pr)}",
            timestamp,
            slug(label),
            artifact.name,
        ]
        if part
    )


def create_oci_par(config: StorageConfig, args: argparse.Namespace, object_key: str) -> str:
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(hours=args.signed_ttl_hours)
    expires_text = expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = run(
        [
            "oci",
            "os",
            "preauth-request",
            "create",
            "--namespace-name",
            config.namespace,
            "--bucket-name",
            config.bucket,
            "--name",
            f"{slug(args.label)}-{slug(args.pr)}",
            "--access-type",
            "ObjectRead",
            "--object-name",
            object_key,
            "--time-expires",
            expires_text,
            "--region",
            config.region,
            "--output",
            "json",
        ],
        capture=True,
    )
    data = json.loads(payload)["data"]
    access_uri = data["access-uri"]
    return f"https://objectstorage.{config.region}.oraclecloud.com{access_uri}"


def stable_marker(repo: str, pr: str, label: str) -> str:
    token = hashlib.sha256(f"{repo}:{pr}:{slug(label)}".encode()).hexdigest()[:16]
    return f"<!-- pr-add-artifact:{token} -->"


def build_comment(args: argparse.Namespace, manifest: dict, display_url: str, marker: str) -> str:
    artifact = manifest["artifact"]
    storage = manifest["storage"]
    title = args.comment_title or f"Artifact: {args.label}"
    lines = [marker, f"### {title}", ""]

    if args.visibility == "public":
        if pathlib.Path(artifact["name"]).suffix.lower() in IMAGE_SUFFIXES:
            lines.extend([f"![{args.label}]({display_url})", ""])
        else:
            lines.append(f"- URL: {display_url}")
    elif args.visibility == "signed":
        lines.append(f"- Signed URL: {display_url}")
        lines.append(f"- Expires: {args.signed_expires or str(args.signed_ttl_hours) + 'h'}")
    else:
        lines.append("- Visibility: private")
        lines.append(f"- Reference: `{storage['ref']}`")

    lines.extend(
        [
            f"- Artifact type: `{args.artifact_type}`",
            f"- Backend: `{storage['backend']}`",
            f"- Bucket: `{storage['bucket']}`",
            f"- Object: `{storage['objectKey']}`",
            f"- SHA-256: `{artifact['sha256']}`",
            f"- Size: `{artifact['sizeBytes']}` bytes",
        ]
    )
    if args.retention:
        lines.append(f"- Retention: {args.retention}")
    return "\n".join(lines) + "\n"


def gh_upsert_comment(repo: str, pr: str, marker: str, body_path: pathlib.Path) -> None:
    comments = json.loads(
        run(["gh", "api", f"repos/{repo}/issues/{pr}/comments", "--paginate"], capture=True) or "[]"
    )
    for comment in comments:
        if marker in comment.get("body", ""):
            run(
                [
                    "gh",
                    "api",
                    f"repos/{repo}/issues/comments/{comment['id']}",
                    "--method",
                    "PATCH",
                    "--field",
                    f"body=@{body_path}",
                ]
            )
            return
    run(["gh", "pr", "comment", pr, "--repo", repo, "--body-file", str(body_path)])


def resolve_display_url(config: StorageConfig, args: argparse.Namespace, object_key: str, uploaded: bool) -> str:
    if args.visibility == "public":
        return public_url(config, object_key)
    if args.visibility != "signed":
        return ""
    if args.signed_url:
        return args.signed_url
    if args.dry_run:
        return f"https://signed.example.invalid/{urllib.parse.quote(object_key)}"
    if config.backend == "s3":
        return presigned_get_url(config, object_key, args.signed_ttl_hours * 3600)
    if config.backend == "oci" and args.create_oci_par:
        if not uploaded:
            raise ValueError("OCI PAR creation requires --upload before signing")
        return create_oci_par(config, args, object_key)
    raise ValueError("Signed live mode requires --signed-url, S3 credentials, or --create-oci-par for OCI")


def publish(args: argparse.Namespace) -> dict:
    config = config_from_args(args)
    source = pathlib.Path(args.file).resolve()
    enforce_public_privacy(source, args)
    timestamp = args.timestamp or dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = pathlib.Path(args.out_dir).resolve() if args.out_dir else pathlib.Path(tempfile.mkdtemp(prefix="pr-add-artifact-"))
    out_dir.mkdir(parents=True, exist_ok=True)

    artifact = stage_artifact(source, out_dir, args.label)
    enforce_max_size(artifact, args.max_bytes)
    object_key = build_object_key(args.prefix, args.repo, args.pr, args.label, artifact, timestamp)
    manifest_key = f"{object_key}.manifest.json"
    artifact_sha = sha256_file(artifact)
    artifact_size = artifact.stat().st_size

    manifest = {
        "schemaVersion": "pr-add-artifact.v1",
        "generatedAt": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "dryRun": args.dry_run,
        "source": {"repo": args.repo, "pr": args.pr, "label": args.label, "path": str(source)},
        "artifact": {
            "name": artifact.name,
            "type": args.artifact_type,
            "sha256": artifact_sha,
            "sizeBytes": artifact_size,
        },
        "storage": {
            "backend": config.backend,
            "visibility": args.visibility,
            "bucket": config.bucket,
            "namespace": config.namespace or None,
            "region": config.region or None,
            "endpointUrl": config.endpoint_url or None,
            "prefix": args.prefix,
            "objectKey": object_key,
            "manifestObjectKey": manifest_key,
            "ref": storage_ref(config, object_key),
        },
    }

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    uploaded = False
    if args.upload and not args.dry_run:
        upload_file(config, artifact, object_key, content_type_for(artifact))
        upload_file(config, manifest_path, manifest_key, "application/json; charset=utf-8")
        uploaded = True

    display_url = resolve_display_url(config, args, object_key, uploaded)
    marker = stable_marker(args.repo, args.pr, args.label)
    comment = build_comment(args, manifest, display_url, marker)
    comment_path = out_dir / "comment.md"
    comment_path.write_text(comment, encoding="utf-8")

    if args.comment and not args.dry_run:
        gh_upsert_comment(args.repo, args.pr, marker, comment_path)

    result = {
        "artifactPath": str(artifact),
        "manifestPath": str(manifest_path),
        "commentPath": str(comment_path),
        "objectKey": object_key,
        "manifestObjectKey": manifest_key,
        "visibility": args.visibility,
        "backend": config.backend,
        "sha256": artifact_sha,
        "displayUrl": display_url,
        "ref": storage_ref(config, object_key),
    }
    result_path = out_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="pr-add-artifact-test-") as tmp:
        root = pathlib.Path(tmp)
        screenshot = root / "screen.png"
        screenshot.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
        sbom = root / "sbom.json"
        sbom.write_text('{"bomFormat":"CycloneDX"}\n', encoding="utf-8")
        report_dir = root / "report"
        report_dir.mkdir()
        (report_dir / "index.html").write_text("<html>ok</html>\n", encoding="utf-8")

        common = [
            "--repo",
            "red-wiz/aphrodite",
            "--pr",
            "205",
            "--backend",
            "s3",
            "--bucket",
            "artifact-bucket",
            "--region",
            "us-east-1",
            "--endpoint-url",
            "http://127.0.0.1:9000",
            "--access-key-id",
            "minioadmin",
            "--secret-access-key",
            "minioadmin",
            "--prefix",
            "aphrodite/test",
            "--timestamp",
            "20260619T000000Z",
            "--dry-run",
        ]

        cases = [
            ["--file", str(screenshot), "--label", "screenshot", "--artifact-type", "screenshot", "--visibility", "public", "--public-base-url", "https://public.example/o"],
            ["--file", str(sbom), "--label", "sbom", "--artifact-type", "sbom", "--visibility", "private"],
            ["--file", str(report_dir), "--label", "report", "--artifact-type", "playwright-report", "--visibility", "signed", "--signed-url", "https://signed.example/report"],
        ]

        for index, extra in enumerate(cases):
            out_dir = root / f"out-{index}"
            args = parse_args(common + extra + ["--out-dir", str(out_dir)])
            result = publish(args)
            body = pathlib.Path(result["commentPath"]).read_text(encoding="utf-8")
            manifest = json.loads(pathlib.Path(result["manifestPath"]).read_text(encoding="utf-8"))
            assert manifest["dryRun"] is True
            assert manifest["storage"]["backend"] == "s3"
            assert manifest["artifact"]["sha256"] == result["sha256"]
            assert "artifact-bucket" in body
            visibility = extra[extra.index("--visibility") + 1]
            if visibility == "private":
                assert "https://" not in body
                assert "Visibility: private" in body
                assert "s3://artifact-bucket/" in body
            if visibility == "public":
                assert "![screenshot]" in body
            if visibility == "signed":
                assert "Signed URL" in body

    print("self-test ok")


def add_storage_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", choices=["s3", "oci"], default=os.environ.get("OBJECT_STORAGE_BACKEND", "s3"))
    parser.add_argument("--bucket", default=os.environ.get("OBJECT_STORAGE_BUCKET", os.environ.get("OCI_OBJECT_STORAGE_BUCKET", "")))
    parser.add_argument("--namespace", default=os.environ.get("OCI_OBJECT_STORAGE_NAMESPACE", os.environ.get("OCI_NAMESPACE", "")))
    parser.add_argument("--region", default=os.environ.get("OBJECT_STORAGE_REGION", os.environ.get("OCI_REGION", os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "")))))
    parser.add_argument("--endpoint-url", default=os.environ.get("OBJECT_STORAGE_ENDPOINT_URL", os.environ.get("AWS_ENDPOINT_URL", "")))
    parser.add_argument("--public-base-url", default=os.environ.get("OBJECT_STORAGE_PUBLIC_BASE_URL", os.environ.get("OCI_OBJECT_STORAGE_PUBLIC_BASE_URL", "")))
    parser.add_argument("--access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", ""))
    parser.add_argument("--secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", ""))
    parser.add_argument("--session-token", default=os.environ.get("AWS_SESSION_TOKEN", ""))
    parser.add_argument("--virtual-hosted-style", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("PR_ARTIFACT_TIMEOUT_SECONDS", "30")))
    parser.add_argument("--retries", type=int, default=int(os.environ.get("PR_ARTIFACT_RETRIES", "2")))


CONFIG_OPTIONS = {
    "backend": ["--backend"],
    "bucket": ["--bucket"],
    "namespace": ["--namespace"],
    "region": ["--region"],
    "endpoint_url": ["--endpoint-url"],
    "public_base_url": ["--public-base-url"],
    "access_key_id": ["--access-key-id"],
    "secret_access_key": ["--secret-access-key"],
    "session_token": ["--session-token"],
    "prefix": ["--prefix"],
    "retention": ["--retention"],
    "visibility": ["--visibility"],
    "artifact_type": ["--artifact-type"],
    "max_bytes": ["--max-bytes"],
    "timeout_seconds": ["--timeout-seconds"],
    "retries": ["--retries"],
}


def option_supplied(argv: list[str], names: list[str]) -> bool:
    for token in argv:
        for name in names:
            if token == name or token.startswith(f"{name}="):
                return True
    return False


def apply_config(args: argparse.Namespace, argv: list[str]) -> None:
    config = load_config(args.config, args.profile)
    if not config:
        return
    for attr, option_names in CONFIG_OPTIONS.items():
        if option_supplied(argv, option_names):
            continue
        if attr in {"access_key_id", "secret_access_key", "session_token"}:
            value = config_secret(config, attr)
        else:
            value = config_value(config, attr)
        if value is None or value == "":
            continue
        current = getattr(args, attr)
        if current in {"", None, "private", "artifact", "pr-artifacts", 0, 2, 30}:
            setattr(args, attr, coerce_config_value(attr, value))

    privacy_checks = config_value(config, "privacy_checks")
    if privacy_checks is not None and not option_supplied(argv, ["--privacy-checks", "--no-privacy-checks"]):
        args.privacy_checks = bool(privacy_checks)


def coerce_config_value(attr: str, value):
    if attr in {"max_bytes", "timeout_seconds", "retries"}:
        return int(value)
    return value


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--config", default=os.environ.get("PR_ARTIFACT_CONFIG", ""))
    parser.add_argument("--profile", default=os.environ.get("PR_ARTIFACT_PROFILE", ""))
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr", default="")
    parser.add_argument("--file", default="")
    parser.add_argument("--label", default="artifact")
    parser.add_argument("--artifact-type", default="artifact")
    parser.add_argument("--visibility", choices=["private", "signed", "public"], default=os.environ.get("PR_ARTIFACT_VISIBILITY", "private"))
    add_storage_args(parser)
    parser.add_argument("--prefix", default="pr-artifacts")
    parser.add_argument("--retention", default="")
    parser.add_argument("--comment-title", default="")
    parser.add_argument("--signed-url", default="")
    parser.add_argument("--signed-expires", default="")
    parser.add_argument("--signed-ttl-hours", type=int, default=24)
    parser.add_argument("--create-oci-par", action="store_true")
    parser.add_argument("--allow-sensitive-public", action="store_true")
    parser.add_argument("--privacy-checks", dest="privacy_checks", action="store_true", default=True)
    parser.add_argument("--no-privacy-checks", dest="privacy_checks", action="store_false")
    parser.add_argument("--max-bytes", type=int, default=int(os.environ.get("PR_ARTIFACT_MAX_BYTES", "0")))
    parser.add_argument("--timestamp", default="")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--comment", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return args
    try:
        apply_config(args, argv)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    missing = [name for name in ["repo", "pr", "file", "bucket"] if not getattr(args, name)]
    if args.backend == "oci" and not args.namespace:
        missing.append("namespace")
    if missing:
        raise SystemExit(f"Missing required arguments: {', '.join('--' + name.replace('_', '-') for name in missing)}")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    try:
        result = publish(args)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(result_json(**result), end="")
    return 0


def with_defaults(argv: list[str], defaults: list[str]) -> list[str]:
    result = list(argv)
    for index in range(0, len(defaults), 2):
        name = defaults[index]
        value = defaults[index + 1]
        if not option_supplied(result, [name]):
            result = [name, value, *result]
    return result


def cli() -> None:
    raise SystemExit(main(sys.argv[1:]))


def cli_screenshot() -> None:
    argv = with_defaults(sys.argv[1:], ["--artifact-type", "screenshot", "--visibility", "public", "--label", "screenshot"])
    raise SystemExit(main(argv))


def cli_test_report() -> None:
    argv = with_defaults(sys.argv[1:], ["--artifact-type", "test-report", "--visibility", "signed", "--label", "test-report"])
    raise SystemExit(main(argv))


def cli_sbom() -> None:
    argv = with_defaults(sys.argv[1:], ["--artifact-type", "sbom", "--visibility", "private", "--label", "sbom"])
    raise SystemExit(main(argv))


if __name__ == "__main__":
    cli()
