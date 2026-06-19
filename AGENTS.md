# Agent Notes

## Purpose

This repo packages Codex skills for adding local artifacts to GitHub pull requests. Keep durable agent workflows here and keep the public `README.md` short.

## Skills

- `pr-add-artifact`: core publisher for files or directories.
- `pr-add-screenshot`: screenshot/image defaults.
- `pr-add-test-report`: Playwright/test report defaults.
- `pr-add-sbom`: private SBOM/provenance defaults.

The core helper lives in `skills/pr-add-artifact/scripts/`. The top-level `lib/python/pr_artifacts/` copy is used by repo tests and release validation.

## Storage Backends

Use `--backend s3` for generic S3-compatible object storage, including MinIO, RustFS, AWS S3, and compatible services. Use `--endpoint-url`, `--access-key-id`, and `--secret-access-key` for local or self-hosted targets.

Use `--backend oci` only when the target is OCI Object Storage and OCI CLI authentication is expected, such as `OCI_CLI_AUTH=instance_principal`.

## Visibility Policy

- `public`: screenshots and intentionally public reports only.
- `signed`: temporary reviewer access for private-ish reports.
- `private`: default for SBOMs, provenance, logs, coverage, traces, and anything that may contain secrets or customer data.

The publisher blocks public `sbom`, `provenance`, `log`, and `coverage` artifacts unless `--allow-sensitive-public` is explicit.

## Local Validation

```sh
make test
python3 -m pip install PyYAML  # if the active Python env does not already have it
./scripts/validate-plugin.sh
npx skills add . --list --full-depth --yes
```

The E2E test uses a local S3-compatible HTTP mock and does not require cloud credentials.

With direnv/devenv:

```sh
direnv allow
devenv test
devenv tasks run demo:gif
devenv tasks run release:package
```

## Demo GIF

The README GIF is generated from a deterministic dry-run transcript:

```sh
./scripts/render-demo-gif.sh
```

`scripts/demo.sh` creates a temporary one-pixel screenshot and prints the generated object key and PR comment preview. `assets/demo.tape` is kept as a VHS source, but `scripts/render-demo-gif.sh` is the portable path when VHS tty startup is unavailable.

## Release

Update `VERSION`, `.codex-plugin/plugin.json`, and release notes together. Then validate and package:

```sh
make test
./scripts/package-release.sh v$(cat VERSION)
```

For a public GitHub release:

```sh
git tag v$(cat VERSION)
git push origin main --tags
gh release create v$(cat VERSION) dist/pr-artifact-skills-v$(cat VERSION).* --repo adrianmross/pr-artifact-skills --title v$(cat VERSION) --notes-file dist/release-notes.md
```

The release workflow also packages and publishes archives when a `v*` tag is pushed.

## Public Install Paths

Skills CLI:

```sh
npx skills add adrianmross/pr-artifact-skills --skill pr-add-artifact -g -y
npx skills add adrianmross/pr-artifact-skills --skill pr-add-screenshot -g -y
npx skills add adrianmross/pr-artifact-skills --skill pr-add-test-report -g -y
npx skills add adrianmross/pr-artifact-skills --skill pr-add-sbom -g -y
```

Codex plugin users can clone or download the release archive and install the plugin from the repo root, which contains `.codex-plugin/plugin.json` and `skills/`.
