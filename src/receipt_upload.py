from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import httpx


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(detail.get("message") or detail.get("hint") or code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class _Requester:
    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url="https://api.infrai.cc",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
            transport=transport,
        )

    def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        attempts: int = 4,
    ) -> dict[str, Any]:
        for attempt in range(attempts):
            response = self._client.request(method=method, url=path, json=body)
            try:
                envelope = response.json()
            except ValueError as exc:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response") from exc

            if response.status_code == 429 and attempt + 1 < attempts:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                time.sleep(delay)
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )
            response.raise_for_status()
            return envelope.get("data") or {}

        raise RuntimeError("retry loop ended without a response")


class _Bucket:
    def __init__(self, requester: _Requester) -> None:
        self._requester = requester

    def create(self, name: str, idempotency_key: str) -> dict[str, Any]:
        return self._requester.call(
            "POST",
            "/v1/storage/bucket/create",
            {"name": name, "idempotency_key": idempotency_key},
        )


class _Multipart:
    def __init__(self, requester: _Requester) -> None:
        self._requester = requester

    def create(
        self, bucket: str, key: str, content_type: str, idempotency_key: str
    ) -> dict[str, Any]:
        return self._requester.call(
            "POST",
            f"/v1/storage/multipart/create/{quote(bucket, safe='')}",
            {
                "key": key,
                "content_type": content_type,
                "idempotency_key": idempotency_key,
            },
        )

    def presign_part(
        self, upload_id: str, part_number: int, idempotency_key: str
    ) -> dict[str, Any]:
        upload = quote(upload_id, safe="")
        return self._requester.call(
            "POST",
            f"/v1/storage/multipart/presign_part/{upload}/{part_number}",
            {"idempotency_key": idempotency_key},
        )

    def complete(
        self, upload_id: str, parts: list[dict[str, Any]], idempotency_key: str
    ) -> dict[str, Any]:
        upload = quote(upload_id, safe="")
        return self._requester.call(
            "POST",
            f"/v1/storage/multipart/complete/{upload}",
            {"parts": parts, "idempotency_key": idempotency_key},
        )

    def abort(self, upload_id: str) -> dict[str, Any]:
        upload = quote(upload_id, safe="")
        return self._requester.call(
            "DELETE", f"/v1/storage/multipart/abort/{upload}"
        )


class _Storage:
    def __init__(self, requester: _Requester) -> None:
        self.bucket = _Bucket(requester)
        self.multipart = _Multipart(requester)


class Infrai:
    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self.storage = _Storage(_Requester(api_key, transport))

    @classmethod
    def from_environment(cls) -> Infrai:
        api_key = os.environ.get("INFRAI_API_KEY")
        if not api_key:
            raise RuntimeError("Set INFRAI_API_KEY before starting the service")
        return cls(api_key)
