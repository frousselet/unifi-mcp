"""Multi-tenant support: encrypted tenant store, client bundles, and a cache.

A *tenant* is one UniFi customer that has onboarded through the web UI. Each
tenant owns:

- an OAuth client (``client_id`` / ``client_secret``) that Claude uses to
  connect to the shared ``/mcp`` endpoint,
- an encrypted UniFi cloud API key,
- optional console IDs so the Network and Protect tools can reach a console
  through the cloud connector.

The store is a single JSON file encrypted field-by-field (the UniFi key and the
OAuth client secret are sealed with Fernet). It also holds short-lived OAuth
authorization codes and issued access/refresh tokens. This is deliberately
simple (file + in-process lock) — fine for a self-hosted single-process
deployment; swap in a real database for scale.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from unifi_mcp.client import UniFiClient
from unifi_mcp.mobility_client import MobilityClient
from unifi_mcp.network_client import NetworkClient
from unifi_mcp.protect_client import ProtectClient

logger = logging.getLogger("unifi-mcp.tenant")


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------


def _load_fernet(key_path: Path) -> Fernet:
    """Build the Fernet cipher used to encrypt secrets at rest.

    Resolution order:
    1. ``UNIFI_SECRET_KEY`` env — a Fernet key, or any passphrase (hashed).
    2. A key file persisted next to the store (auto-generated on first run so
       ``docker compose up`` needs no configuration yet survives restarts).
    """
    raw = os.environ.get("UNIFI_SECRET_KEY", "")
    if raw:
        try:
            return Fernet(raw)
        except (ValueError, TypeError):
            digest = hashlib.sha256(raw.encode()).digest()
            return Fernet(base64.urlsafe_b64encode(digest))

    # No env key: persist a generated one next to the store.
    if key_path.exists():
        return Fernet(key_path.read_bytes().strip())
    key = Fernet.generate_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    logger.info(
        "Generated and persisted an encryption key at %s. Keep this file (and "
        "the data volume) safe; set UNIFI_SECRET_KEY to override.",
        key_path,
    )
    return Fernet(key)


# ---------------------------------------------------------------------------
# Client bundle (the four API clients for one tenant or the env config)
# ---------------------------------------------------------------------------


@dataclass
class ClientBundle:
    """The set of UniFi API clients used to serve one caller."""

    site_manager: UniFiClient
    mobility: MobilityClient
    network: NetworkClient | None
    protect: ProtectClient | None

    async def aclose(self) -> None:
        await self.site_manager.close()
        await self.mobility.close()
        if self.network:
            await self.network.close()
        if self.protect:
            await self.protect.close()

    @classmethod
    def from_config(
        cls,
        api_key: str,
        *,
        network_console_id: str | None = None,
        protect_console_id: str | None = None,
        network_host: str | None = None,
        protect_host: str | None = None,
        timeout: float | None = None,
    ) -> "ClientBundle":
        """Build a bundle from explicit credentials (no env reads for identity).

        Network/Protect clients are only created when a console ID or host is
        supplied for them; otherwise those tools are unavailable for the tenant.
        """
        site_manager = UniFiClient(api_key=api_key, timeout=timeout)
        mobility = MobilityClient(api_key=api_key, timeout=timeout)

        network: NetworkClient | None = None
        if network_console_id or network_host:
            network = NetworkClient(
                host=network_host or None,
                console_id=network_console_id or None,
                api_key=api_key,
                timeout=timeout,
            )

        protect: ProtectClient | None = None
        if protect_console_id or protect_host:
            protect = ProtectClient(
                host=protect_host or None,
                console_id=protect_console_id or None,
                api_key=api_key,
                timeout=timeout,
            )

        return cls(
            site_manager=site_manager,
            mobility=mobility,
            network=network,
            protect=protect,
        )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class Tenant:
    tenant_id: str
    client_id: str
    client_secret: str  # decrypted in memory
    api_key: str  # decrypted in memory
    owner_id: str = ""
    label: str = ""
    network_console_id: str = ""
    protect_console_id: str = ""
    created_at: int = 0


@dataclass
class OAuthCode:
    code: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    scopes: list[str] = field(default_factory=list)
    expires_at: float = 0.0


@dataclass
class OAuthTokenRecord:
    token: str
    client_id: str
    scopes: list[str] = field(default_factory=list)
    expires_at: float = 0.0


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class TenantStore:
    """Encrypted, file-backed store for tenants and OAuth state."""

    def __init__(self, path: str | None = None):
        self._path = Path(
            path
            or os.environ.get("UNIFI_TENANT_STORE", "")
            or "/data/unifi_tenants.json"
        )
        self._fernet = _load_fernet(self._path.with_name("secret.key"))
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] = {
            "tenants": {},  # tenant_id -> record dict
            "admins": {},  # admin_id -> {email, created_at}
            "credentials": {},  # credential_id(b64url) -> passkey record
            "codes": {},  # sha256(code) -> record dict
            "tokens": {},  # sha256(access token) -> record dict
            "refresh": {},  # sha256(refresh token) -> sha256(access token)
        }
        self._load()
        # Ensure new collections exist when loading an older store file.
        for key in ("tenants", "admins", "credentials", "codes", "tokens", "refresh"):
            self._data.setdefault(key, {})

    # --- persistence ---

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Failed to read tenant store %s: %s", self._path, e)

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self._path)

    def _enc(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def _dec(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()

    @staticmethod
    def _hash(token: str) -> str:
        """Hash a bearer secret for storage.

        Access/refresh tokens and authorization codes are high-entropy random
        strings, so a plain SHA-256 is sufficient (no salt needed) and means the
        raw, usable secret is never written to disk.
        """
        return hashlib.sha256(token.encode()).hexdigest()

    # --- tenants ---

    async def create_tenant(
        self,
        api_key: str,
        *,
        owner_id: str = "",
        label: str = "",
        network_console_id: str = "",
        protect_console_id: str = "",
    ) -> Tenant:
        async with self._lock:
            tenant_id = "ten_" + secrets.token_hex(8)
            client_id = "unifi_" + secrets.token_hex(12)
            client_secret = secrets.token_urlsafe(32)
            record = {
                "tenant_id": tenant_id,
                "client_id": client_id,
                "client_secret_enc": self._enc(client_secret),
                "api_key_enc": self._enc(api_key),
                "owner_id": owner_id,
                "label": label,
                "network_console_id": network_console_id,
                "protect_console_id": protect_console_id,
                "created_at": int(time.time()),
            }
            self._data["tenants"][tenant_id] = record
            self._flush()
            return self._to_tenant(record)

    def _to_tenant(self, record: dict[str, Any]) -> Tenant:
        return Tenant(
            tenant_id=record["tenant_id"],
            client_id=record["client_id"],
            client_secret=self._dec(record["client_secret_enc"]),
            api_key=self._dec(record["api_key_enc"]),
            owner_id=record.get("owner_id", ""),
            label=record.get("label", ""),
            network_console_id=record.get("network_console_id", ""),
            protect_console_id=record.get("protect_console_id", ""),
            created_at=record.get("created_at", 0),
        )

    def get_tenant_by_client_id(self, client_id: str) -> Tenant | None:
        for record in self._data["tenants"].values():
            if record["client_id"] == client_id:
                return self._to_tenant(record)
        return None

    def list_tenants(self, owner_id: str | None = None) -> list[dict[str, Any]]:
        """Return non-secret metadata for tenants, optionally scoped to an owner."""
        out: list[dict[str, Any]] = []
        for record in self._data["tenants"].values():
            if owner_id is not None and record.get("owner_id", "") != owner_id:
                continue
            out.append(
                {
                    "tenant_id": record["tenant_id"],
                    "client_id": record["client_id"],
                    "owner_id": record.get("owner_id", ""),
                    "label": record.get("label", ""),
                    "network_console_id": record.get("network_console_id", ""),
                    "protect_console_id": record.get("protect_console_id", ""),
                    "created_at": record.get("created_at", 0),
                }
            )
        out.sort(key=lambda r: r["created_at"], reverse=True)
        return out

    async def delete_tenant(self, tenant_id: str, owner_id: str | None = None) -> bool:
        """Delete a tenant and revoke its OAuth tokens.

        When ``owner_id`` is given, the tenant is only deleted if it belongs to
        that owner (so users can only revoke their own connections).
        """
        async with self._lock:
            record = self._data["tenants"].get(tenant_id)
            if record is None:
                return False
            if owner_id is not None and record.get("owner_id", "") != owner_id:
                return False
            self._data["tenants"].pop(tenant_id, None)
            # Drop any tokens/refresh tokens issued to this tenant's client.
            client_id = record["client_id"]
            for tok, rec in list(self._data["tokens"].items()):
                if rec.get("client_id") == client_id:
                    self._data["tokens"].pop(tok, None)
            self._flush()
            return True

    # --- Admins & passkey credentials ---

    def has_admin(self) -> bool:
        return bool(self._data["admins"])

    async def create_admin(self, email: str) -> str:
        async with self._lock:
            admin_id = "adm_" + secrets.token_hex(8)
            self._data["admins"][admin_id] = {
                "email": email,
                "created_at": int(time.time()),
            }
            self._flush()
            return admin_id

    def get_admin(self, admin_id: str) -> dict[str, Any] | None:
        return self._data["admins"].get(admin_id)

    async def add_credential(
        self,
        admin_id: str,
        credential_id: str,
        public_key: str,
        sign_count: int,
        transports: list[str] | None = None,
    ) -> None:
        """Store a passkey. ``credential_id``/``public_key`` are base64url text.

        Passkey public keys are not secret, so they are stored as-is.
        """
        async with self._lock:
            self._data["credentials"][credential_id] = {
                "admin_id": admin_id,
                "public_key": public_key,
                "sign_count": sign_count,
                "transports": transports or [],
            }
            self._flush()

    def get_credential(self, credential_id: str) -> dict[str, Any] | None:
        return self._data["credentials"].get(credential_id)

    def list_credential_ids(self) -> list[str]:
        return list(self._data["credentials"].keys())

    async def update_sign_count(self, credential_id: str, sign_count: int) -> None:
        async with self._lock:
            rec = self._data["credentials"].get(credential_id)
            if rec is not None:
                rec["sign_count"] = sign_count
                self._flush()

    # --- OAuth codes (stored by hash) ---

    async def save_code(self, code: OAuthCode) -> None:
        async with self._lock:
            self._data["codes"][self._hash(code.code)] = {
                "client_id": code.client_id,
                "redirect_uri": code.redirect_uri,
                "code_challenge": code.code_challenge,
                "scopes": code.scopes,
                "expires_at": code.expires_at,
            }
            self._flush()

    def get_code(self, code: str) -> OAuthCode | None:
        rec = self._data["codes"].get(self._hash(code))
        if not rec:
            return None
        return OAuthCode(code=code, **rec)

    async def pop_code(self, code: str) -> None:
        async with self._lock:
            self._data["codes"].pop(self._hash(code), None)
            self._flush()

    # --- OAuth tokens (stored by hash) ---

    async def save_token(
        self, record: OAuthTokenRecord, refresh_token: str | None = None
    ) -> None:
        async with self._lock:
            self._data["tokens"][self._hash(record.token)] = {
                "client_id": record.client_id,
                "scopes": record.scopes,
                "expires_at": record.expires_at,
            }
            if refresh_token:
                self._data["refresh"][self._hash(refresh_token)] = self._hash(
                    record.token
                )
            self._flush()

    def get_token(self, token: str) -> OAuthTokenRecord | None:
        rec = self._data["tokens"].get(self._hash(token))
        if not rec:
            return None
        return OAuthTokenRecord(token=token, **rec)

    def get_token_by_hash(self, token_hash: str) -> OAuthTokenRecord | None:
        rec = self._data["tokens"].get(token_hash)
        if not rec:
            return None
        # The raw token is unknown (only its hash is stored); token field unused.
        return OAuthTokenRecord(token="", **rec)

    def get_refresh_access_hash(self, refresh_token: str) -> str | None:
        """Return the hash of the access token behind a refresh token, if any."""
        return self._data["refresh"].get(self._hash(refresh_token))

    async def revoke(self, token: str) -> None:
        """Revoke by raw token (access or refresh)."""
        await self._revoke_hash(self._hash(token))

    async def _revoke_hash(self, token_hash: str) -> None:
        async with self._lock:
            self._data["tokens"].pop(token_hash, None)
            self._data["refresh"].pop(token_hash, None)
            # Drop any refresh token that maps to this access-token hash.
            for rt_hash, at_hash in list(self._data["refresh"].items()):
                if at_hash == token_hash:
                    self._data["refresh"].pop(rt_hash, None)
            self._flush()


# ---------------------------------------------------------------------------
# Bundle registry (one cached ClientBundle per tenant)
# ---------------------------------------------------------------------------


class BundleRegistry:
    """Lazily builds and caches a ClientBundle per tenant client_id."""

    def __init__(self, store: TenantStore):
        self._store = store
        self._bundles: dict[str, ClientBundle] = {}

    def bundle_for_client_id(self, client_id: str) -> ClientBundle | None:
        if client_id in self._bundles:
            return self._bundles[client_id]
        tenant = self._store.get_tenant_by_client_id(client_id)
        if tenant is None:
            return None
        bundle = ClientBundle.from_config(
            api_key=tenant.api_key,
            network_console_id=tenant.network_console_id or None,
            protect_console_id=tenant.protect_console_id or None,
        )
        self._bundles[client_id] = bundle
        return bundle

    async def aclose(self) -> None:
        for bundle in self._bundles.values():
            await bundle.aclose()
        self._bundles.clear()
