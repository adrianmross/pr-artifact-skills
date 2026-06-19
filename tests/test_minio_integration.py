#!/usr/bin/env python3
"""Optional MinIO integration test for S3-compatible behavior."""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
import urllib.request

import publish_pr_artifact


def minio_env() -> dict[str, str]:
    return {
        "endpoint": os.environ.get("PR_ARTIFACT_MINIO_ENDPOINT", ""),
        "bucket": os.environ.get("PR_ARTIFACT_MINIO_BUCKET", "pr-artifacts"),
        "access_key": os.environ.get("PR_ARTIFACT_MINIO_ACCESS_KEY", "minioadmin"),
        "secret_key": os.environ.get("PR_ARTIFACT_MINIO_SECRET_KEY", "minioadmin"),
        "public_base_url": os.environ.get("PR_ARTIFACT_MINIO_PUBLIC_BASE_URL", ""),
    }


@unittest.skipUnless(os.environ.get("PR_ARTIFACT_MINIO_ENDPOINT"), "PR_ARTIFACT_MINIO_ENDPOINT not set")
class MinioIntegrationTests(unittest.TestCase):
    def test_upload_and_presigned_download(self) -> None:
        env = minio_env()
        with tempfile.TemporaryDirectory(prefix="publish-minio-") as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "screen.png"
            artifact.write_bytes(b"minio artifact")
            args = publish_pr_artifact.parse_args(
                [
                    "--repo",
                    "adrianmross/example",
                    "--pr",
                    "42",
                    "--file",
                    str(artifact),
                    "--label",
                    "minio",
                    "--artifact-type",
                    "screenshot",
                    "--visibility",
                    "signed",
                    "--backend",
                    "s3",
                    "--bucket",
                    env["bucket"],
                    "--region",
                    "us-east-1",
                    "--endpoint-url",
                    env["endpoint"],
                    "--access-key-id",
                    env["access_key"],
                    "--secret-access-key",
                    env["secret_key"],
                    "--prefix",
                    "integration",
                    "--timestamp",
                    "20260619T000000Z",
                    "--upload",
                    "--out-dir",
                    str(root / "out"),
                ]
            )
            result = publish_pr_artifact.publish(args)
            self.assertIn("X-Amz-Signature=", result["displayUrl"])
            with urllib.request.urlopen(result["displayUrl"], timeout=10) as response:
                self.assertEqual(response.read(), b"minio artifact")

            manifest_path = pathlib.Path(result["manifestPath"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["storage"]["backend"], "s3")
            self.assertEqual(manifest["storage"]["bucket"], env["bucket"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
