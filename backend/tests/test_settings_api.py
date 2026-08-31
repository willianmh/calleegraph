"""API-level tests for GET/PUT /api/settings (backend prompt §5)."""

from __future__ import annotations

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.main import app


@pytest.fixture
async def client() -> httpx.AsyncClient:
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def test_get_settings_defaults(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "pat_set": False,
        "github_actor_login": None,
        "github_api_version": "2022-11-28",
        "github_api_base": "https://api.github.com",
    }


async def test_put_settings_valid_pat_stores_encrypted_and_never_echoes(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer ghp_valid"
        assert request.url.path == "/user"
        return httpx.Response(200, json={"login": "octocat"})

    import app.routers.settings as settings_module

    class FakeClient:
        def __init__(self, token: str, **kwargs: object) -> None:
            self._transport = httpx.MockTransport(handler)
            self._inner = httpx.AsyncClient(transport=self._transport, base_url="https://api.github.com")
            self.token = token

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            await self._inner.aclose()

        async def get_user(self) -> dict:
            resp = await self._inner.get("/user", headers={"Authorization": f"Bearer {self.token}"})
            return resp.json()

    monkeypatch.setattr(settings_module, "GitHubClient", FakeClient)

    resp = await client.put("/api/settings", json={"github_pat": "ghp_valid"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["pat_set"] is True
    assert body["github_actor_login"] == "octocat"
    assert "github_pat" not in body
    assert "ghp_valid" not in resp.text

    # A second GET reflects the persisted state without ever exposing the PAT.
    resp2 = await client.get("/api/settings")
    assert resp2.json()["pat_set"] is True
    assert "ghp_valid" not in resp2.text


async def test_put_settings_invalid_pat_rejected(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.routers.settings as settings_module
    from app.github.client import GitHubError

    class FailingClient:
        def __init__(self, token: str, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> FailingClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def get_user(self) -> dict:
            raise GitHubError("Bad credentials", status=401)

    monkeypatch.setattr(settings_module, "GitHubClient", FailingClient)

    resp = await client.put("/api/settings", json={"github_pat": "ghp_bad"})
    assert resp.status_code == 400
    assert "Invalid GitHub PAT" in resp.json()["detail"]

    # Rejected PAT must not be stored.
    resp2 = await client.get("/api/settings")
    assert resp2.json()["pat_set"] is False


async def test_put_settings_updates_api_version_and_base_without_pat(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.put(
        "/api/settings",
        json={"github_api_version": "2023-01-01", "github_api_base": "https://ghe.example.com/api/v3"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["github_api_version"] == "2023-01-01"
    assert body["github_api_base"] == "https://ghe.example.com/api/v3"
    assert body["pat_set"] is False
