"""OAuth 2.1 Authorization Server provider backed by the tenant store.

Implements the ``OAuthAuthorizationServerProvider`` protocol from the MCP SDK.
Each tenant onboarded through the web UI owns one confidential OAuth client
(``client_id`` / ``client_secret``). Claude presents those credentials, runs the
authorization-code + PKCE flow against ``/authorize`` and ``/token`` (mounted by
FastMCP when this provider is configured), and receives an access token that is
bound to the tenant's ``client_id``. Tool calls then resolve the tenant from the
token via :class:`~unifi_mcp.tenant.BundleRegistry`.

PKCE verification and redirect-URI membership checks are performed by the SDK's
handlers; this provider only mints and validates codes/tokens.
"""

from __future__ import annotations

import logging
import os
import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from unifi_mcp.tenant import OAuthCode, OAuthTokenRecord, TenantStore

logger = logging.getLogger("unifi-mcp.oauth")

SCOPE = "unifi"
CODE_TTL = 300  # 5 minutes
ACCESS_TTL = 3600  # 1 hour
REFRESH_TTL = 60 * 60 * 24 * 30  # 30 days

# Redirect URIs allowed for tenant OAuth clients. Claude's web connector uses a
# fixed callback; override/extend via UNIFI_OAUTH_REDIRECT_URIS (comma list).
_DEFAULT_REDIRECTS = [
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
]


def _redirect_uris() -> list[str]:
    raw = os.environ.get("UNIFI_OAUTH_REDIRECT_URIS", "")
    if raw.strip():
        return [u.strip() for u in raw.split(",") if u.strip()]
    return list(_DEFAULT_REDIRECTS)


class UniFiOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, store: TenantStore):
        self._store = store

    # --- Clients ---

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        tenant = self._store.get_tenant_by_client_id(client_id)
        if tenant is None:
            return None
        return OAuthClientInformationFull(
            client_id=tenant.client_id,
            client_secret=tenant.client_secret,
            redirect_uris=_redirect_uris(),  # type: ignore[arg-type]
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=SCOPE,
            client_name=tenant.label or "UniFi MCP tenant",
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # Dynamic client registration is disabled for this deployment; tenants
        # are created through the onboarding web UI. No-op to satisfy the protocol.
        raise NotImplementedError("Dynamic client registration is disabled.")

    # --- Authorization codes ---

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        code = "code_" + secrets.token_urlsafe(24)
        await self._store.save_code(
            OAuthCode(
                code=code,
                client_id=client.client_id,
                redirect_uri=str(params.redirect_uri),
                code_challenge=params.code_challenge,
                scopes=params.scopes or [SCOPE],
                expires_at=time.time() + CODE_TTL,
            )
        )
        return construct_redirect_uri(
            str(params.redirect_uri), code=code, state=params.state
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        rec = self._store.get_code(authorization_code)
        if rec is None or rec.client_id != client.client_id:
            return None
        if rec.expires_at < time.time():
            await self._store.pop_code(authorization_code)
            return None
        return AuthorizationCode(
            code=rec.code,
            scopes=rec.scopes,
            expires_at=rec.expires_at,
            client_id=rec.client_id,
            code_challenge=rec.code_challenge,
            redirect_uri=rec.redirect_uri,  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=True,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        await self._store.pop_code(authorization_code.code)
        return await self._issue_tokens(client.client_id, authorization_code.scopes)

    # --- Refresh tokens ---

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        access_hash = self._store.get_refresh_access_hash(refresh_token)
        if access_hash is None:
            return None
        rec = self._store.get_token_by_hash(access_hash)
        if rec is None or rec.client_id != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=rec.scopes,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Rotate: revoke the old access token behind this refresh token, and the
        # refresh token itself (both are stored only as hashes).
        old_access_hash = self._store.get_refresh_access_hash(refresh_token.token)
        if old_access_hash:
            await self._store._revoke_hash(old_access_hash)
        await self._store.revoke(refresh_token.token)
        return await self._issue_tokens(
            client.client_id, scopes or refresh_token.scopes
        )

    # --- Access tokens ---

    async def load_access_token(self, token: str) -> AccessToken | None:
        rec = self._store.get_token(token)
        if rec is None:
            return None
        if rec.expires_at < time.time():
            await self._store.revoke(token)
            return None
        return AccessToken(
            token=token,
            client_id=rec.client_id,
            scopes=rec.scopes,
            expires_at=int(rec.expires_at),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await self._store.revoke(token.token)

    # --- helpers ---

    async def _issue_tokens(self, client_id: str, scopes: list[str]) -> OAuthToken:
        access = "at_" + secrets.token_urlsafe(32)
        refresh = "rt_" + secrets.token_urlsafe(32)
        now = time.time()
        await self._store.save_token(
            OAuthTokenRecord(
                token=access,
                client_id=client_id,
                scopes=scopes,
                expires_at=now + ACCESS_TTL,
            ),
            refresh_token=refresh,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TTL,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )
