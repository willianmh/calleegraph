"""Async GitHub REST client (httpx).

This slice only needs PAT validation (``GET /user``), so that's all that's
implemented here. Rate limits are respected by honoring ``Retry-After`` and
the ``x-ratelimit-remaining``/``x-ratelimit-reset`` headers with a bounded
backoff — carried over from Runbook's client since repo-tree listing and
blob/content fetch (backend prompt §6) will extend this same class.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GitHubError(Exception):
    """A GitHub REST call failed. ``status`` is the HTTP status if available."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GitHubClient:
    """Thin async wrapper over the GitHub REST API."""

    def __init__(
        self,
        token: str,
        *,
        api_base: str = "https://api.github.com",
        api_version: str = "2022-11-28",
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
    ) -> None:
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._api_version = api_version
        self._max_retries = max_retries
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": self._api_version,
        }

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = path if path.startswith("http") else f"{self._api_base}{path}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.request(
                    method, url, headers=self._headers, params=params, json=json
                )
            except httpx.HTTPError as exc:  # network-level failure
                last_exc = exc
                if attempt >= self._max_retries:
                    raise GitHubError(f"network error calling GitHub: {exc}") from exc
                await asyncio.sleep(min(2**attempt, 8))
                continue

            # Rate-limit / secondary-limit handling.
            if resp.status_code in (403, 429) and self._should_backoff(resp):
                delay = self._retry_delay(resp)
                if attempt < self._max_retries and delay is not None:
                    logger.warning("GitHub rate limited; backing off %.1fs", delay)
                    await asyncio.sleep(min(delay, 30))
                    continue
            return resp
        # Unreachable, but keeps mypy happy.
        raise GitHubError(f"exhausted retries calling GitHub: {last_exc}")

    @staticmethod
    def _should_backoff(resp: httpx.Response) -> bool:
        if "retry-after" in resp.headers:
            return True
        return resp.headers.get("x-ratelimit-remaining") == "0"

    @staticmethod
    def _retry_delay(resp: httpx.Response) -> float | None:
        retry_after = resp.headers.get("retry-after")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                return None
        reset = resp.headers.get("x-ratelimit-reset")
        if reset is not None:
            try:
                return max(0.0, float(reset) - time.time())
            except ValueError:
                return None
        return None

    @staticmethod
    def _raise_for(resp: httpx.Response, context: str) -> None:
        if resp.is_success:
            return
        detail = context
        try:
            body = resp.json()
            if isinstance(body, dict) and body.get("message"):
                detail = f"{context}: {body['message']}"
        except Exception:  # noqa: BLE001 - best-effort detail extraction
            pass
        raise GitHubError(detail, status=resp.status_code)

    # --- Endpoints ---

    async def get_user(self) -> dict[str, Any]:
        """``GET /user`` — validates the PAT and returns the authenticated user."""
        resp = await self._request("GET", "/user")
        self._raise_for(resp, "PAT validation failed")
        return resp.json()
