#!/usr/bin/env python3
"""Local E2E tests for publish_pr_artifact and S3-compatible object storage."""

from __future__ import annotations

import http.server
import json
import pathlib
import socketserver
import tempfile
import threading
import unittest

import publish_pr_artifact


class Store:
    objects: dict[str, bytes] = {}
    headers: dict[str, dict[str, str]] = {}
    failures_remaining: int = 0


class S3LikeHandler(http.server.BaseHTTPRequestHandler):
    def do_PUT(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        if Store.failures_remaining > 0:
            Store.failures_remaining -= 1
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"try again")
            return
        Store.objects[self.path] = body
        Store.headers[self.path] = {key.lower(): value for key, value in self.headers.items()}
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        body = Store.objects.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class PublishArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        Store.objects = {}
        Store.headers = {}
        Store.failures_remaining = 0
        cls.server = ThreadedServer(("127.0.0.1", 0), S3LikeHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def test_s3_upload_stores_artifact_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="publish-e2e-") as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "screen.png"
            artifact.write_bytes(b"not-really-a-png")
            out_dir = root / "out"

            args = publish_pr_artifact.parse_args(
                [
                    "--repo",
                    "red-wiz/aphrodite",
                    "--pr",
                    "205",
                    "--file",
                    str(artifact),
                    "--label",
                    "screenshot",
                    "--artifact-type",
                    "screenshot",
                    "--visibility",
                    "public",
                    "--backend",
                    "s3",
                    "--bucket",
                    "artifacts",
                    "--region",
                    "us-east-1",
                    "--endpoint-url",
                    self.endpoint,
                    "--access-key-id",
                    "minioadmin",
                    "--secret-access-key",
                    "minioadmin",
                    "--prefix",
                    "e2e",
                    "--timestamp",
                    "20260619T000000Z",
                    "--upload",
                    "--out-dir",
                    str(out_dir),
                ]
            )

            result = publish_pr_artifact.publish(args)
            artifact_path = f"/artifacts/{result['objectKey']}"
            manifest_path = f"/artifacts/{result['manifestObjectKey']}"

            self.assertIn(artifact_path, Store.objects)
            self.assertIn(manifest_path, Store.objects)
            self.assertEqual(Store.objects[artifact_path], b"not-really-a-png")
            self.assertIn("authorization", Store.headers[artifact_path])
            self.assertTrue(Store.headers[artifact_path]["authorization"].startswith("AWS4-HMAC-SHA256 "))

            manifest = json.loads(Store.objects[manifest_path].decode("utf-8"))
            self.assertEqual(manifest["storage"]["backend"], "s3")
            self.assertEqual(manifest["storage"]["ref"], f"s3://artifacts/{result['objectKey']}")

    def test_config_file_provides_storage_defaults(self) -> None:
        with tempfile.TemporaryDirectory(prefix="publish-e2e-") as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "screen.png"
            artifact.write_bytes(b"png")
            config = root / ".pr-artifacts.yaml"
            config.write_text(
                "\n".join(
                    [
                        "storage:",
                        "  backend: s3",
                        "  bucket: artifacts",
                        "  region: us-east-1",
                        f"  endpoint_url: {self.endpoint}",
                        "  access_key_id: minioadmin",
                        "  secret_access_key: minioadmin",
                        "defaults:",
                        "  visibility: public",
                        "  prefix: configured",
                        "  max_bytes: 100",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            args = publish_pr_artifact.parse_args(
                [
                    "--config",
                    str(config),
                    "--repo",
                    "red-wiz/aphrodite",
                    "--pr",
                    "205",
                    "--file",
                    str(artifact),
                    "--label",
                    "configured screenshot",
                    "--artifact-type",
                    "screenshot",
                    "--timestamp",
                    "20260619T000000Z",
                    "--dry-run",
                    "--out-dir",
                    str(root / "out"),
                ]
            )
            result = publish_pr_artifact.publish(args)
            self.assertEqual(result["backend"], "s3")
            self.assertEqual(result["visibility"], "public")
            self.assertTrue(result["objectKey"].startswith("configured/"))

    def test_retry_succeeds_after_transient_s3_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="publish-e2e-") as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "screen.png"
            artifact.write_bytes(b"retry")
            Store.failures_remaining = 1
            args = publish_pr_artifact.parse_args(
                [
                    "--repo",
                    "red-wiz/aphrodite",
                    "--pr",
                    "205",
                    "--file",
                    str(artifact),
                    "--label",
                    "retry",
                    "--artifact-type",
                    "screenshot",
                    "--visibility",
                    "public",
                    "--backend",
                    "s3",
                    "--bucket",
                    "artifacts",
                    "--region",
                    "us-east-1",
                    "--endpoint-url",
                    self.endpoint,
                    "--access-key-id",
                    "minioadmin",
                    "--secret-access-key",
                    "minioadmin",
                    "--prefix",
                    "e2e",
                    "--timestamp",
                    "20260619T000000Z",
                    "--upload",
                    "--retries",
                    "1",
                    "--out-dir",
                    str(root / "out"),
                ]
            )
            result = publish_pr_artifact.publish(args)
            self.assertIn(f"/artifacts/{result['objectKey']}", Store.objects)

    def test_max_bytes_guard(self) -> None:
        with tempfile.TemporaryDirectory(prefix="publish-e2e-") as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "large.txt"
            artifact.write_bytes(b"12345")
            args = publish_pr_artifact.parse_args(
                [
                    "--repo",
                    "red-wiz/aphrodite",
                    "--pr",
                    "205",
                    "--file",
                    str(artifact),
                    "--label",
                    "large",
                    "--artifact-type",
                    "artifact",
                    "--visibility",
                    "private",
                    "--backend",
                    "s3",
                    "--bucket",
                    "artifacts",
                    "--max-bytes",
                    "4",
                    "--dry-run",
                ]
            )
            with self.assertRaisesRegex(ValueError, "exceeding --max-bytes"):
                publish_pr_artifact.publish(args)

    def test_private_comment_has_no_url(self) -> None:
        with tempfile.TemporaryDirectory(prefix="publish-e2e-") as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "sbom.json"
            artifact.write_text('{"bomFormat":"CycloneDX"}\n', encoding="utf-8")
            out_dir = root / "out"
            args = publish_pr_artifact.parse_args(
                [
                    "--repo",
                    "red-wiz/aphrodite",
                    "--pr",
                    "205",
                    "--file",
                    str(artifact),
                    "--label",
                    "sbom",
                    "--artifact-type",
                    "sbom",
                    "--visibility",
                    "private",
                    "--backend",
                    "s3",
                    "--bucket",
                    "artifacts",
                    "--region",
                    "us-east-1",
                    "--endpoint-url",
                    self.endpoint,
                    "--access-key-id",
                    "minioadmin",
                    "--secret-access-key",
                    "minioadmin",
                    "--prefix",
                    "e2e",
                    "--timestamp",
                    "20260619T000000Z",
                    "--dry-run",
                    "--out-dir",
                    str(out_dir),
                ]
            )
            result = publish_pr_artifact.publish(args)
            body = pathlib.Path(result["commentPath"]).read_text(encoding="utf-8")
            self.assertIn("Visibility: private", body)
            self.assertIn("s3://artifacts/", body)
            self.assertNotIn("https://", body)
            self.assertNotIn("http://", body)

    def test_sensitive_public_guard(self) -> None:
        with tempfile.TemporaryDirectory(prefix="publish-e2e-") as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "sbom.json"
            artifact.write_text('{"bomFormat":"CycloneDX"}\n', encoding="utf-8")
            args = publish_pr_artifact.parse_args(
                [
                    "--repo",
                    "red-wiz/aphrodite",
                    "--pr",
                    "205",
                    "--file",
                    str(artifact),
                    "--label",
                    "sbom",
                    "--artifact-type",
                    "sbom",
                    "--visibility",
                    "public",
                    "--backend",
                    "s3",
                    "--bucket",
                    "artifacts",
                    "--region",
                    "us-east-1",
                    "--endpoint-url",
                    self.endpoint,
                    "--access-key-id",
                    "minioadmin",
                    "--secret-access-key",
                    "minioadmin",
                    "--dry-run",
                ]
            )
            with self.assertRaisesRegex(ValueError, "defaults to private"):
                publish_pr_artifact.publish(args)

    def test_sensitive_filename_public_guard(self) -> None:
        with tempfile.TemporaryDirectory(prefix="publish-e2e-") as tmp:
            root = pathlib.Path(tmp)
            artifact = root / ".env"
            artifact.write_text("TOKEN=secret\n", encoding="utf-8")
            args = publish_pr_artifact.parse_args(
                [
                    "--repo",
                    "red-wiz/aphrodite",
                    "--pr",
                    "205",
                    "--file",
                    str(artifact),
                    "--label",
                    "env",
                    "--artifact-type",
                    "screenshot",
                    "--visibility",
                    "public",
                    "--backend",
                    "s3",
                    "--bucket",
                    "artifacts",
                    "--dry-run",
                ]
            )
            with self.assertRaisesRegex(ValueError, "looks sensitive"):
                publish_pr_artifact.publish(args)

    def test_sensitive_content_public_guard(self) -> None:
        with tempfile.TemporaryDirectory(prefix="publish-e2e-") as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "notes.txt"
            artifact.write_text("API_KEY=abcd1234secretvalue\n", encoding="utf-8")
            args = publish_pr_artifact.parse_args(
                [
                    "--repo",
                    "red-wiz/aphrodite",
                    "--pr",
                    "205",
                    "--file",
                    str(artifact),
                    "--label",
                    "notes",
                    "--artifact-type",
                    "artifact",
                    "--visibility",
                    "public",
                    "--backend",
                    "s3",
                    "--bucket",
                    "artifacts",
                    "--dry-run",
                ]
            )
            with self.assertRaisesRegex(ValueError, "content looks sensitive"):
                publish_pr_artifact.publish(args)


if __name__ == "__main__":
    unittest.main(verbosity=2)
