"""Unit tests for GitHubClient (backend prompt §5 PAT validation path)."""

from __future__ import annotations

import httpx
import pytest

from app.github.client import GitHubClient, GitHubError


async def test_get_user_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer ghp_testtoken"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        return httpx.Response(200, json={"login": "octocat", "id": 1})

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient("ghp_testtoken", client=http_client)
    try:
        user = await client.get_user()
        assert user["login"] == "octocat"
    finally:
        await http_client.aclose()


async def test_get_user_bad_credentials_raises_github_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient("ghp_bad", client=http_client)
    try:
        with pytest.raises(GitHubError) as exc_info:
            await client.get_user()
        assert "Bad credentials" in str(exc_info.value)
        assert exc_info.value.status == 401
    finally:
        await http_client.aclose()


async def test_rate_limit_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                403,
                headers={"retry-after": "0", "x-ratelimit-remaining": "0"},
                json={"message": "rate limited"},
            )
        return httpx.Response(200, json={"login": "octocat"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient("ghp_testtoken", client=http_client)
    try:
        user = await client.get_user()
        assert user["login"] == "octocat"
        assert calls["n"] == 2
    finally:
        await http_client.aclose()
