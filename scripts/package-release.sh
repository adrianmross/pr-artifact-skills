#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-v$(cat VERSION)}"
NAME="pr-artifact-skills-${VERSION}"
DIST_DIR="dist"

mkdir -p "$DIST_DIR"

git archive --format=tar --prefix="${NAME}/" HEAD | gzip -n > "${DIST_DIR}/${NAME}.tar.gz"
git archive --format=zip --prefix="${NAME}/" HEAD -o "${DIST_DIR}/${NAME}.zip"

cat > "${DIST_DIR}/release-notes.md" <<NOTES
## ${VERSION}

PR Artifact Skills release.

- Codex plugin manifest with four bundled skills.
- Skills CLI install support for screenshot, test report, SBOM, and generic artifact workflows.
- S3-compatible storage by default, including MinIO and RustFS.
- OCI Object Storage path for OCI CLI and instance principal environments.
- Explicit public, signed, and private visibility modes.
- Reproducible devenv/direnv development shell.
- First-class Python console scripts, repo config files, CI validation, MinIO integration coverage, and upload guardrails.
NOTES

printf '%s\n' "${DIST_DIR}/${NAME}.tar.gz"
printf '%s\n' "${DIST_DIR}/${NAME}.zip"
