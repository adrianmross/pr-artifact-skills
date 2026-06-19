---
name: pr-add-artifact
description: Add a local artifact such as a screenshot, Playwright report, SBOM, provenance, coverage, log, or other PR evidence to a GitHub pull request by uploading it to durable object storage and adding or updating a PR comment. Use when Codex needs reusable agent-side artifact publishing with explicit public, signed, or private visibility across S3-compatible storage, MinIO, RustFS, OCI Object Storage, or GitHub PR comments instead of hard-wiring uploads into CI.
---

# PR Add Artifact

Use this skill when an agent has a local file or directory and needs to publish it for a pull request. Prefer this agent-side flow over adding repo-specific CI upload wiring unless the artifact must be produced inside CI.

This skill is installed locally at `~/.codex/skills/pr-add-artifact`. That makes it available to this machine's Codex skill loader after reload. To share it with other machines or agents, copy this folder into a git repo and install it with `npx skills add <owner/repo@pr-add-artifact>`, or wrap it in a Codex plugin.

## Components

- `scripts/object_store.py`: dependency-free storage library with `s3` and `oci` backends.
- `scripts/oos_cli.py`: simple object-storage CLI for `put`, `ref`, `public-url`, and `presign-get`.
- `scripts/publish_pr_artifact.py`: end-to-end artifact staging, manifest creation, upload, and PR comment upsert.
- `scripts/test_publish_pr_artifact.py`: local S3-compatible E2E tests using a localhost mock server.

## Visibility

Choose visibility before uploading:

- `private`: default for `sbom`, `provenance`, `log`, `coverage`, and unknown sensitive artifacts. The PR comment includes metadata, digest, and a storage reference, but no URL.
- `signed`: use for private artifacts that reviewers need to fetch temporarily. For S3-compatible backends, the helper can generate SigV4 presigned GET URLs. For OCI, provide a signed URL or use `--create-oci-par`.
- `public`: use only for low-risk screenshots and reports intended to be directly visible from the PR comment.

When unsure, choose `private`.

## Backends

Prefer `--backend s3` for generic object storage. It works with S3-compatible services such as MinIO and RustFS using `--endpoint-url`, `--access-key-id`, and `--secret-access-key`.

Use `--backend oci` when relying on OCI CLI auth such as `OCI_CLI_AUTH=instance_principal`. OCI still uses OCI-shaped references such as `oci://n/<namespace>/b/<bucket>/o/<key>`.

## Examples

Dry-run public screenshot to S3-compatible storage:

```sh
python3 /Users/adross/.codex/skills/pr-add-artifact/scripts/publish_pr_artifact.py \
  --repo red-wiz/aphrodite \
  --pr 205 \
  --file /path/to/screenshot.png \
  --label "JSON-LD screenshot" \
  --artifact-type screenshot \
  --visibility public \
  --backend s3 \
  --bucket pr-artifacts \
  --endpoint-url http://127.0.0.1:9000 \
  --access-key-id minioadmin \
  --secret-access-key minioadmin \
  --prefix aphrodite/playwright \
  --dry-run
```

Live private SBOM to OCI using instance principal:

```sh
OCI_CLI_AUTH=instance_principal \
python3 /Users/adross/.codex/skills/pr-add-artifact/scripts/publish_pr_artifact.py \
  --repo red-wiz/aphrodite \
  --pr 205 \
  --file /path/to/sbom.json \
  --label "SBOM evidence" \
  --artifact-type sbom \
  --visibility private \
  --backend oci \
  --bucket red-wiz-codex-test-harness-artifacts \
  --namespace oabcs1 \
  --region us-sanjose-1 \
  --prefix aphrodite/sbom \
  --upload \
  --comment
```

Use the lower-level object-storage CLI when no PR comment is needed:

```sh
python3 /Users/adross/.codex/skills/pr-add-artifact/scripts/oos_cli.py put \
  --backend s3 \
  --bucket pr-artifacts \
  --endpoint-url http://127.0.0.1:9000 \
  --access-key-id minioadmin \
  --secret-access-key minioadmin \
  --file /path/to/report.tgz \
  --key aphrodite/playwright/report.tgz
```

## Comments

The publisher uses a stable marker derived from repository, PR number, and label. In live comment mode it updates an existing bot/user comment with the same marker, or creates one if none exists. This avoids repeated comment spam.

Private comments must not include public URLs. They should include:

- visibility
- backend
- bucket
- object key
- SHA-256
- size
- retention if provided
- storage reference, such as `s3://bucket/key` or `oci://n/ns/b/bucket/o/key`

Public screenshot comments may embed the image directly. Signed comments should show expiration.

## Validation

Run these after editing the skill:

```sh
python3 /Users/adross/.codex/skills/pr-add-artifact/scripts/publish_pr_artifact.py --self-test
python3 /Users/adross/.codex/skills/pr-add-artifact/scripts/test_publish_pr_artifact.py
```

The self-test performs dry-run checks for public screenshot, private SBOM, and signed report comments. The E2E test starts a localhost S3-compatible mock server and verifies signed PUT upload of both artifact and manifest.
