---
name: pr-add-sbom
description: Add a local SBOM, provenance document, signing evidence, or supply-chain report to a GitHub pull request through private object storage and a metadata-only PR comment. Use for CycloneDX, SPDX, SLSA/provenance, attestation, vulnerability, and security-adjacent artifacts that should not be public by default.
---

# PR Add SBOM

Use this thin skill for SBOM and supply-chain evidence. Prefer the `pr-add-sbom` CLI when installed; otherwise delegate to `~/.codex/skills/pr-add-artifact/scripts/publish_pr_artifact.py`.

Default behavior:

- `artifact-type`: `sbom` or `provenance`
- recommended visibility: `private`
- public publishing is blocked by the shared helper unless `--allow-sensitive-public` is explicitly passed
- PR comment should include storage reference, SHA-256, object key, retention, and no public URL

Example:

```sh
pr-add-sbom \
  --repo red-wiz/aphrodite \
  --pr 205 \
  --file /path/to/sbom.cdx.json \
  --label "SBOM evidence" \
  --backend s3 \
  --bucket pr-artifacts \
  --endpoint-url http://127.0.0.1:9000 \
  --access-key-id minioadmin \
  --secret-access-key minioadmin \
  --prefix sbom \
  --retention 30d \
  --upload \
  --comment
```

Use `--backend oci` with `OCI_CLI_AUTH=instance_principal` when the evidence must land in OCI Object Storage under a VM or workload principal.
