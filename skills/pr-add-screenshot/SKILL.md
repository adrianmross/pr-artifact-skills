---
name: pr-add-screenshot
description: Add a local screenshot or image to a GitHub pull request by uploading it through the shared pr-add-artifact object-storage helper and adding or updating a PR comment. Use for screenshots, visual evidence, Playwright screenshots, before/after images, and UI review images where public, signed, or private visibility should be explicit.
---

# PR Add Screenshot

Use this thin skill for the easy screenshot path. Prefer the `pr-add-screenshot` CLI when installed; otherwise delegate to `~/.codex/skills/pr-add-artifact/scripts/publish_pr_artifact.py`.

Default behavior:

- `artifact-type`: `screenshot`
- recommended visibility: `public` for non-sensitive UI screenshots, `signed` for private review, `private` when the image may expose secrets or customer data
- comment: image embed for `public`, signed link for `signed`, metadata-only reference for `private`

Example:

```sh
pr-add-screenshot \
  --repo red-wiz/aphrodite \
  --pr 205 \
  --file /path/to/screenshot.png \
  --label "Login screenshot" \
  --backend s3 \
  --bucket pr-artifacts \
  --endpoint-url http://127.0.0.1:9000 \
  --access-key-id minioadmin \
  --secret-access-key minioadmin \
  --prefix screenshots \
  --upload \
  --comment
```

Use `$pr-add-artifact` directly when the screenshot needs unusual storage, retention, or comment metadata.
