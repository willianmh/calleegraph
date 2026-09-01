"""Async GitHub REST client (httpx).

Covers PAT validation (``GET /user``), repo metadata, branch HEAD lookup, and
workflow discovery via the Git Trees + Blobs APIs (backend prompt §6). Rate
limits are respected by honoring ``Retry-After`` and the
``x-ratelimit-remaining``/``x-ratelimit-reset`` headers with a bounded backoff.

Discovery deliberately uses **one** recursive tree call per repo rather than
walking directories with the contents API, which would cost one request per
directory and burn through rate limits on large repos.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
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
        token: str | None,
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
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self._api_version,
        }
        # No PAT is a supported mode: public repos are readable
        # unauthenticated, just at a much lower rate limit.
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

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

    async def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        """``GET /repos/{owner}/{repo}`` — reachability check + default branch."""
        resp = await self._request("GET", f"/repos/{owner}/{repo}")
        self._raise_for(resp, f"cannot read repository {owner}/{repo}")
        return resp.json()

    async def get_branch_head_sha(self, owner: str, repo: str, branch: str) -> str:
        """Current commit SHA at the tip of ``branch``.

        Uses the git-ref endpoint rather than ``/commits/{branch}`` because the
        payload is a few hundred bytes instead of a full commit object.
        """
        resp = await self._request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
        self._raise_for(resp, f"cannot resolve {owner}/{repo}@{branch}")
        body = resp.json()
        sha = (body.get("object") or {}).get("sha")
        if not isinstance(sha, str) or not sha:
            raise GitHubError(f"malformed ref response for {owner}/{repo}@{branch}")
        return sha

    async def get_tree(self, owner: str, repo: str, sha: str) -> dict[str, Any]:
        """``GET /git/trees/{sha}?recursive=1`` — every path in the repo, one call."""
        resp = await self._request(
            "GET", f"/repos/{owner}/{repo}/git/trees/{sha}", params={"recursive": "1"}
        )
        self._raise_for(resp, f"cannot list tree for {owner}/{repo}@{sha}")
        return resp.json()

    async def get_blob_text(self, owner: str, repo: str, blob_sha: str) -> str:
        """``GET /git/blobs/{sha}`` → decoded UTF-8 text."""
        resp = await self._request("GET", f"/repos/{owner}/{repo}/git/blobs/{blob_sha}")
        self._raise_for(resp, f"cannot read blob {blob_sha} in {owner}/{repo}")
        body = resp.json()
        content = body.get("content") or ""
        encoding = body.get("encoding", "base64")
        if encoding != "base64":
            raise GitHubError(f"unexpected blob encoding {encoding!r} for {blob_sha}")
        try:
            raw = base64.b64decode(content)
        except (binascii.Error, ValueError) as exc:
            raise GitHubError(f"undecodable blob {blob_sha} in {owner}/{repo}: {exc}") from exc
        return raw.decode("utf-8", errors="replace")
