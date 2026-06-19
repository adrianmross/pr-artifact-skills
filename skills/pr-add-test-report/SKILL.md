---
name: pr-add-test-report
description: Add a local test report, Playwright report, trace bundle, coverage report, or test artifact directory to a GitHub pull request through object storage and a PR comment. Use when Codex needs to publish a report directory or archive with public, signed, or private visibility, especially for Playwright HTML reports and retained test evidence.
---

# PR Add Test Report

Use this thin skill for test report directories or archives. Prefer the `pr-add-test-report` CLI when installed; otherwise delegate to `~/.codex/skills/pr-add-artifact/scripts/publish_pr_artifact.py`.

Default behavior:

- `artifact-type`: `playwright-report` or `test-report`
- recommended visibility: `signed` for reviewer-friendly temporary access, `private` for logs/traces/coverage, `public` only for intentionally public HTML reports
- directories are archived once before upload

Example:

```sh
pr-add-test-report \
  --repo red-wiz/aphrodite \
  --pr 205 \
  --file /path/to/playwright-report \
  --label "Playwright report" \
  --backend s3 \
  --bucket pr-artifacts \
  --endpoint-url http://127.0.0.1:9000 \
  --access-key-id minioadmin \
  --secret-access-key minioadmin \
  --prefix test-reports \
  --upload \
  --comment
```

Prefer `private` when the report includes logs, request payloads, traces, source maps, local paths, or customer data.
