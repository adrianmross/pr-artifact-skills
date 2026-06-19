# PR Artifact Skills

Local and publishable skills for adding artifacts to GitHub pull requests.

## Skills

- `pr-add-artifact`: generic artifact publisher.
- `pr-add-screenshot`: screenshot/image defaults.
- `pr-add-test-report`: test report and Playwright report defaults.
- `pr-add-sbom`: private SBOM/provenance defaults.

## Backends

- `s3`: S3-compatible object storage such as MinIO, RustFS, AWS S3, and similar services.
- `oci`: OCI Object Storage through the OCI CLI, including instance principal auth.

## Local Test

```sh
make test
```

The E2E test uses a local HTTP mock for S3-compatible signed PUTs and does not require live cloud credentials.

## Install Locally

Copy or sync each folder in `skills/` into `~/.codex/skills/`.

```sh
rsync -a skills/pr-add-artifact/ ~/.codex/skills/pr-add-artifact/
rsync -a skills/pr-add-screenshot/ ~/.codex/skills/pr-add-screenshot/
rsync -a skills/pr-add-test-report/ ~/.codex/skills/pr-add-test-report/
rsync -a skills/pr-add-sbom/ ~/.codex/skills/pr-add-sbom/
```

To publish for other machines, push this repo and install skills with the Skills CLI once the repository is reachable.
