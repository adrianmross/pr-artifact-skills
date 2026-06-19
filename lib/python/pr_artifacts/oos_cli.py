#!/usr/bin/env python3
"""CLI for simple OCI and S3-compatible object storage operations."""

from __future__ import annotations

import argparse
import pathlib
import sys

try:
    from .object_store import config_from_args, presigned_get_url, public_url, result_json, storage_ref, upload_file
except ImportError:
    from object_store import config_from_args, presigned_get_url, public_url, result_json, storage_ref, upload_file


def add_storage_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", choices=["s3", "oci"], default="s3")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--region", default="")
    parser.add_argument("--namespace", default="")
    parser.add_argument("--endpoint-url", default="")
    parser.add_argument("--public-base-url", default="")
    parser.add_argument("--access-key-id", default="")
    parser.add_argument("--secret-access-key", default="")
    parser.add_argument("--session-token", default="")
    parser.add_argument("--virtual-hosted-style", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    put = sub.add_parser("put")
    add_storage_args(put)
    put.add_argument("--file", required=True)
    put.add_argument("--key", required=True)
    put.add_argument("--content-type", default="")
    put.add_argument("--dry-run", action="store_true")

    ref = sub.add_parser("ref")
    add_storage_args(ref)
    ref.add_argument("--key", required=True)

    pub = sub.add_parser("public-url")
    add_storage_args(pub)
    pub.add_argument("--key", required=True)

    pre = sub.add_parser("presign-get")
    add_storage_args(pre)
    pre.add_argument("--key", required=True)
    pre.add_argument("--expires-seconds", type=int, default=3600)

    args = parser.parse_args(argv)
    config = config_from_args(args)

    try:
        if args.command == "put":
            if not args.dry_run:
                upload_file(config, pathlib.Path(args.file), args.key, args.content_type)
            print(
                result_json(
                    backend=config.backend,
                    bucket=config.bucket,
                    key=args.key,
                    ref=storage_ref(config, args.key),
                    publicUrl=public_url(config, args.key),
                    dryRun=args.dry_run,
                ),
                end="",
            )
        elif args.command == "ref":
            print(storage_ref(config, args.key))
        elif args.command == "public-url":
            print(public_url(config, args.key))
        elif args.command == "presign-get":
            print(presigned_get_url(config, args.key, args.expires_seconds))
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    return 0


def cli() -> None:
    raise SystemExit(main(sys.argv[1:]))


if __name__ == "__main__":
    cli()
