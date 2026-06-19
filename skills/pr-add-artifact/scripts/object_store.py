#!/usr/bin/env python3
"""Small dependency-free object storage helpers for OCI CLI and S3-compatible APIs."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import hmac
import http.client
import json
import mimetypes
import os
import pathlib
import subprocess
import urllib.parse


@dataclass
class StorageConfig:
    backend: str
    bucket: str
    region: str = ""
    namespace: str = ""
    endpoint_url: str = ""
    public_base_url: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    session_token: str = ""
    path_style: bool = True


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote_key(key: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="") for part in key.split("/"))


def content_type_for(path: pathlib.Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def storage_ref(config: StorageConfig, key: str) -> str:
    if config.backend == "oci":
        return f"oci://n/{config.namespace}/b/{config.bucket}/o/{key}"
    if config.backend == "s3":
        return f"s3://{config.bucket}/{key}"
    raise ValueError(f"Unsupported storage backend: {config.backend}")


def public_url(config: StorageConfig, key: str) -> str:
    encoded_key = quote_key(key)
    if config.public_base_url:
        return f"{config.public_base_url.rstrip('/')}/{encoded_key}"

    if config.backend == "oci":
        if not config.region:
            return storage_ref(config, key)
        return (
            f"https://objectstorage.{config.region}.oraclecloud.com/"
            f"n/{urllib.parse.quote(config.namespace, safe='')}/"
            f"b/{urllib.parse.quote(config.bucket, safe='')}/o/{encoded_key}"
        )

    if config.backend == "s3":
        endpoint = config.endpoint_url.rstrip("/")
        if endpoint:
            if config.path_style:
                return f"{endpoint}/{urllib.parse.quote(config.bucket, safe='')}/{encoded_key}"
            parsed = urllib.parse.urlsplit(endpoint)
            return urllib.parse.urlunsplit(
                (parsed.scheme, f"{config.bucket}.{parsed.netloc}", f"/{encoded_key}", "", "")
            )
        return f"https://{config.bucket}.s3.{config.region or 'us-east-1'}.amazonaws.com/{encoded_key}"

    raise ValueError(f"Unsupported storage backend: {config.backend}")


def run(argv: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        argv,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() if capture and result.stderr else ""
        raise RuntimeError(f"{' '.join(argv)} failed with status {result.returncode}{': ' + detail if detail else ''}")
    return result.stdout.strip() if capture and result.stdout else ""


def upload_file(config: StorageConfig, file_path: pathlib.Path, key: str, content_type: str = "") -> None:
    media_type = content_type or content_type_for(file_path)
    if config.backend == "oci":
        upload_file_oci(config, file_path, key, media_type)
        return
    if config.backend == "s3":
        upload_file_s3(config, file_path, key, media_type)
        return
    raise ValueError(f"Unsupported storage backend: {config.backend}")


def upload_file_oci(config: StorageConfig, file_path: pathlib.Path, key: str, content_type: str) -> None:
    if not config.namespace:
        raise ValueError("OCI backend requires namespace")
    command = [
        "oci",
        "os",
        "object",
        "put",
        "--namespace-name",
        config.namespace,
        "--bucket-name",
        config.bucket,
        "--name",
        key,
        "--file",
        str(file_path),
        "--content-type",
        content_type,
        "--force",
    ]
    if config.region:
        command.extend(["--region", config.region])
    run(command)


def upload_file_s3(config: StorageConfig, file_path: pathlib.Path, key: str, content_type: str) -> None:
    url, host = s3_object_url(config, key)
    parsed = urllib.parse.urlsplit(url)
    now = dt.datetime.now(dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_scope = now.strftime("%Y%m%d")
    payload_hash = sha256_file(file_path)
    headers = {
        "content-type": content_type,
        "host": host,
        "content-length": str(file_path.stat().st_size),
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if config.session_token:
        headers["x-amz-security-token"] = config.session_token
    headers["authorization"] = s3_authorization(config, "PUT", key, "", headers, payload_hash, date_scope)
    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_cls(parsed.netloc, timeout=30)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    try:
        connection.putrequest("PUT", target, skip_host=True, skip_accept_encoding=True)
        for name, value in headers.items():
            connection.putheader(name, value)
        connection.endheaders()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                connection.send(chunk)
        response = connection.getresponse()
        body = response.read().decode("utf-8", "replace")
        if response.status not in {200, 201, 204}:
            raise RuntimeError(f"S3 PUT {url} returned HTTP {response.status}: {body}")
    finally:
        connection.close()


def s3_object_url(config: StorageConfig, key: str) -> tuple[str, str]:
    endpoint = config.endpoint_url.rstrip("/") or f"https://s3.{config.region or 'us-east-1'}.amazonaws.com"
    parsed = urllib.parse.urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("--endpoint-url must include scheme and host for S3-compatible storage")

    encoded_key = quote_key(key)
    if config.path_style:
        path = "/".join(part.strip("/") for part in [parsed.path, urllib.parse.quote(config.bucket, safe=""), encoded_key] if part.strip("/"))
        url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, f"/{path}", "", ""))
        return url, parsed.netloc

    host = f"{config.bucket}.{parsed.netloc}"
    path = "/".join(part.strip("/") for part in [parsed.path, encoded_key] if part.strip("/"))
    url = urllib.parse.urlunsplit((parsed.scheme, host, f"/{path}", "", ""))
    return url, host


def s3_authorization(
    config: StorageConfig,
    method: str,
    key: str,
    query: str,
    headers: dict[str, str],
    payload_hash: str,
    date_scope: str,
) -> str:
    if not config.access_key_id or not config.secret_access_key:
        raise ValueError("S3 backend requires access key id and secret access key")
    signed_header_names = sorted(name.lower() for name in headers)
    canonical_headers = "".join(f"{name}:{headers[name].strip()}\n" for name in signed_header_names)
    signed_headers = ";".join(signed_header_names)
    canonical_uri = urllib.parse.urlsplit(s3_object_url(config, key)[0]).path or "/"
    credential_scope = f"{date_scope}/{config.region or 'us-east-1'}/s3/aws4_request"
    canonical_request = "\n".join(
        [method, canonical_uri, query, canonical_headers, signed_headers, payload_hash]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            headers["x-amz-date"],
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = hmac.new(
        s3_signing_key(config.secret_access_key, date_scope, config.region or "us-east-1"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return (
        f"AWS4-HMAC-SHA256 Credential={config.access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


def s3_signing_key(secret_key: str, date_scope: str, region: str) -> bytes:
    def sign(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

    key = sign(("AWS4" + secret_key).encode("utf-8"), date_scope)
    key = sign(key, region)
    key = sign(key, "s3")
    return sign(key, "aws4_request")


def presigned_get_url(config: StorageConfig, key: str, expires_seconds: int = 3600) -> str:
    if config.backend != "s3":
        raise ValueError("presigned_get_url currently supports S3-compatible backends")
    if not config.access_key_id or not config.secret_access_key:
        raise ValueError("S3 backend requires access key id and secret access key")

    now = dt.datetime.now(dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_scope = now.strftime("%Y%m%d")
    credential_scope = f"{date_scope}/{config.region or 'us-east-1'}/s3/aws4_request"
    url, host = s3_object_url(config, key)
    parsed = urllib.parse.urlsplit(url)
    query_pairs = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{config.access_key_id}/{credential_scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires_seconds),
        "X-Amz-SignedHeaders": "host",
    }
    if config.session_token:
        query_pairs["X-Amz-Security-Token"] = config.session_token
    canonical_query = urllib.parse.urlencode(sorted(query_pairs.items()), quote_via=urllib.parse.quote)
    canonical_headers = f"host:{host}\n"
    canonical_request = "\n".join(
        ["GET", parsed.path or "/", canonical_query, canonical_headers, "host", "UNSIGNED-PAYLOAD"]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = hmac.new(
        s3_signing_key(config.secret_access_key, date_scope, config.region or "us-east-1"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, f"{canonical_query}&X-Amz-Signature={signature}", "")
    )


def config_from_args(args) -> StorageConfig:
    return StorageConfig(
        backend=args.backend,
        bucket=args.bucket,
        region=args.region,
        namespace=getattr(args, "namespace", ""),
        endpoint_url=getattr(args, "endpoint_url", ""),
        public_base_url=getattr(args, "public_base_url", ""),
        access_key_id=getattr(args, "access_key_id", "") or os.environ.get("AWS_ACCESS_KEY_ID", ""),
        secret_access_key=getattr(args, "secret_access_key", "") or os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        session_token=getattr(args, "session_token", "") or os.environ.get("AWS_SESSION_TOKEN", ""),
        path_style=not getattr(args, "virtual_hosted_style", False),
    )


def result_json(**kwargs) -> str:
    return json.dumps(kwargs, indent=2, sort_keys=True) + "\n"
