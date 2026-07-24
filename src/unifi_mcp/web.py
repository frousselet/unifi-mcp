"""Multi-user onboarding web app + combined ASGI server (passwordless).

``unifi-mcp-web`` serves, on a single port, with **no configuration required**:

- ``/register`` / ``/login``  → passwordless accounts (WebAuthn passkeys only)
- ``/``                       → the signed-in user's connections + a form to add one
- ``POST /onboard``           → creates a connection → MCP URL + OAuth id/secret
- ``POST /connections/delete``→ revoke one of your connections
- ``/mcp``                    → the shared, OAuth-protected MCP endpoint
- ``/authorize`` ``/token`` ``/.well-known/oauth-*`` → OAuth 2.1 server

Anyone can self-register (optionally gated by ``UNIFI_ONBOARD_CODE``). Each user
owns as many MCP connections as they like and can revoke them at any time. The
public base URL is auto-detected from the request, and the encryption key is
auto-generated and persisted — so ``docker compose up`` works out of the box.
"""

from __future__ import annotations

import html
import json as _jsonmod
import logging
import os
import secrets
from urllib.parse import urlparse

# The web app is inherently multi-tenant; force the mode before importing the
# server module (which reads UNIFI_MULTITENANT at import time).
os.environ.setdefault("UNIFI_MULTITENANT", "1")

from starlette.middleware.sessions import SessionMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import (  # noqa: E402
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from starlette.routing import Route  # noqa: E402
from webauthn import (  # noqa: E402
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url  # noqa: E402
from webauthn.helpers.structs import (  # noqa: E402
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from unifi_mcp import server  # noqa: E402
from unifi_mcp.oauth import SCOPE, _redirect_uris  # noqa: E402

logger = logging.getLogger("unifi-mcp.web")

mcp = server.mcp

# Session signing key for the browser cookie (WebAuthn challenges + login state).
_SESSION_SECRET = os.environ.get("UNIFI_SECRET_KEY") or secrets.token_urlsafe(32)


def _store():
    return server.STORE


def _base_url(request: Request) -> str:
    """The public base URL, auto-detected from the request (honoring proxies).

    ``UNIFI_PUBLIC_URL`` overrides detection when set — recommended in
    production so OAuth 401 hints match exactly.
    """
    env = os.environ.get("UNIFI_PUBLIC_URL")
    if env:
        return env.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    return f"{proto}://{host}"


def _rp_id(request: Request) -> str:
    return urlparse(_base_url(request)).hostname or "localhost"


def _rp_name() -> str:
    return os.environ.get("UNIFI_RP_NAME", "UniFi MCP")


def _uid(request: Request) -> str | None:
    return request.session.get("uid")


def _json(options) -> dict:
    return _jsonmod.loads(options_to_json(options))


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UniFi MCP</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, sans-serif; max-width: 680px; margin: 2.5rem auto;
         padding: 0 1rem; line-height: 1.5; }}
  h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.15rem; margin-top: 2rem; }}
  label {{ display:block; margin-top: 1rem; font-weight: 600; }}
  input {{ width: 100%; padding: .6rem; margin-top: .3rem; box-sizing: border-box;
          border: 1px solid #8888; border-radius: 6px; font-size: 1rem;
          background: transparent; color: inherit; }}
  small {{ color: #888; font-weight: 400; }}
  button {{ margin-top: 1.2rem; padding: .7rem 1.2rem; font-size: 1rem;
           border-radius: 6px; border: 0; background: #2d6cdf; color: #fff;
           cursor: pointer; }}
  .card {{ border: 1px solid #8884; border-radius: 10px; padding: 1.1rem 1.3rem;
          margin-top: 1rem; }}
  code {{ background: #8882; padding: .15rem .4rem; border-radius: 4px;
         word-break: break-all; }}
  .row {{ margin: .7rem 0; }}
  .muted {{ color:#888; font-size:.9rem; }}
  .err {{ color:#c0392b; }}
  .top {{ display:flex; justify-content:space-between; align-items:center; }}
  table {{ width:100%; border-collapse:collapse; }}
  th, td {{ text-align:left; padding:.45rem .3rem; border-bottom:1px solid #8883;
           vertical-align:top; }}
</style></head><body>
{body}
</body></html>"""

_WEBAUTHN_JS = """
<script>
function b64urlToBuf(s){s=s.replace(/-/g,'+').replace(/_/g,'/');const p=s.length%4;
 if(p)s+='='.repeat(4-p);const b=atob(s);const u=new Uint8Array(b.length);
 for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return u.buffer;}
function bufToB64url(buf){const u=new Uint8Array(buf);let s='';
 for(const b of u)s+=String.fromCharCode(b);
 return btoa(s).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'');}
async function postJSON(url,body){const r=await fetch(url,{method:'POST',
 headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
 if(!r.ok)throw new Error((await r.json()).error||('HTTP '+r.status));return r.json();}
function setErr(m){const e=document.getElementById('err');if(e)e.textContent=m||'';}
async function doRegister(email,code){
 setErr('');
 const opts=await postJSON('/webauthn/register/begin',{email:email,code:code});
 opts.challenge=b64urlToBuf(opts.challenge);opts.user.id=b64urlToBuf(opts.user.id);
 if(opts.excludeCredentials)for(const c of opts.excludeCredentials)c.id=b64urlToBuf(c.id);
 const cred=await navigator.credentials.create({publicKey:opts});
 await postJSON('/webauthn/register/complete',{credential:{
   id:cred.id,rawId:bufToB64url(cred.rawId),type:cred.type,
   clientExtensionResults:cred.getClientExtensionResults?cred.getClientExtensionResults():{},
   response:{clientDataJSON:bufToB64url(cred.response.clientDataJSON),
    attestationObject:bufToB64url(cred.response.attestationObject),
    transports:cred.response.getTransports?cred.response.getTransports():[]}}});
 location.href='/';
}
async function doLogin(){
 setErr('');
 const opts=await postJSON('/webauthn/login/begin',{});
 opts.challenge=b64urlToBuf(opts.challenge);
 if(opts.allowCredentials)for(const c of opts.allowCredentials)c.id=b64urlToBuf(c.id);
 const cred=await navigator.credentials.get({publicKey:opts});const r=cred.response;
 await postJSON('/webauthn/login/complete',{credential:{
   id:cred.id,rawId:bufToB64url(cred.rawId),type:cred.type,
   clientExtensionResults:cred.getClientExtensionResults?cred.getClientExtensionResults():{},
   response:{clientDataJSON:bufToB64url(r.clientDataJSON),
    authenticatorData:bufToB64url(r.authenticatorData),
    signature:bufToB64url(r.signature),
    userHandle:r.userHandle?bufToB64url(r.userHandle):null}}});
 location.href='/';
}
</script>
"""


def _page(body: str) -> str:
    return _PAGE.format(body=body)


def _register_page() -> str:
    code_field = ""
    if os.environ.get("UNIFI_ONBOARD_CODE"):
        code_field = (
            '<label>Invite code<input id="code" autocomplete="off" required></label>'
        )
    body = f"""
<h1>Create your account</h1>
<p class="muted">Passwordless — secure your account with a passkey (Touch ID,
Windows Hello, a security key, or your phone).</p>
<p id="err" class="err"></p>
<div class="card">
  <label>Email<input id="email" type="email" required placeholder="you@example.com"></label>
  {code_field}
  <button onclick="const e=document.getElementById('email').value.trim();
    const c=document.getElementById('code')?document.getElementById('code').value.trim():'';
    if(!e){{setErr('Enter an email.');return;}}
    doRegister(e,c).catch(x=>setErr(x.message))">Create passkey</button>
</div>
<p class="muted">Already have an account? <a href="/login">Sign in</a></p>
{_WEBAUTHN_JS}
"""
    return _page(body)


def _login_page() -> str:
    body = f"""
<h1>Sign in</h1>
<p id="err" class="err"></p>
<div class="card">
  <button onclick="doLogin().catch(x=>setErr(x.message))">Sign in with passkey</button>
</div>
<p class="muted">No account yet? <a href="/register">Create one</a></p>
{_WEBAUTHN_JS}
"""
    return _page(body)


def _dashboard_page(email: str, tenants: list[dict], error: str = "") -> str:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    if tenants:
        rows = "".join(
            f"<tr><td>{html.escape(t['label'] or '—')}<br>"
            f"<small class='muted'>Client ID: <code>{html.escape(t['client_id'])}</code></small></td>"
            f"<td><code>{html.escape(t['network_console_id'] or '—')}</code></td>"
            f'<td><form method="post" action="/connections/delete" style="margin:0" '
            f"onsubmit=\"return confirm('Revoke this connection? Claude will lose access.')\">"
            f'<input type="hidden" name="tenant_id" value="{html.escape(t["tenant_id"])}">'
            f'<button style="background:#c0392b;margin:0;padding:.35rem .7rem">Revoke</button>'
            f"</form></td></tr>"
            for t in tenants
        )
        table = (
            "<table><tr><th>Connection</th><th>Console</th><th></th></tr>"
            + rows
            + "</table>"
        )
    else:
        table = "<p class='muted'>No connections yet. Create your first one below.</p>"

    gate = ""
    if os.environ.get("UNIFI_ONBOARD_CODE"):
        gate = (
            '<label>Onboarding code<input name="onboard_code" required '
            'autocomplete="off"></label>'
        )
    body = f"""
<div class="top"><h1>Your connections</h1>
  <span class="muted">{html.escape(email)} · <a href="/logout">Sign out</a></span></div>
{err}
<div class="card">{table}</div>

<h2>Add a connection</h2>
<p class="muted">Each connection maps one UniFi API key to an MCP endpoint for
Claude. Create a key at <a href="https://unifi.ui.com">unifi.ui.com → API</a>.
The connection can reach <b>every console your account owns</b>; pick a default
below (tools also accept a <code>console_id</code> to target any other).</p>
<p id="err" class="err"></p>
<form method="post" action="/onboard" class="card">
  {gate}
  <label>UniFi API key <small>(required)</small>
    <input name="api_key" id="api_key" required autocomplete="off" placeholder="0HMN…XvWC"></label>
  <label>Default console <small>(optional — enables Network &amp; Protect tools)</small>
    <div style="display:flex;gap:.5rem;align-items:flex-end">
      <select name="console_id" id="console_id" style="flex:1;padding:.6rem;border-radius:6px;
        border:1px solid #8888;background:transparent;color:inherit;font-size:1rem">
        <option value="">(load consoles →)</option>
      </select>
      <button type="button" onclick="loadConsoles().catch(e=>setErr(e.message))"
        style="margin:0;background:#555">Load consoles</button>
    </div></label>
  <label>Label <small>(optional)</small>
    <input name="label" autocomplete="off" placeholder="Home network"></label>
  <button type="submit">Create connection</button>
</form>
<script>
function setErr(m){{const e=document.getElementById('err');if(e)e.textContent=m||'';}}
async function loadConsoles(){{
  setErr('');
  const k=document.getElementById('api_key').value.trim();
  if(!k){{setErr('Enter your API key first.');return;}}
  const r=await fetch('/hosts',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{api_key:k}})}});
  const j=await r.json();
  if(!r.ok){{setErr(j.error||'Failed to load consoles');return;}}
  const sel=document.getElementById('console_id');sel.innerHTML='';
  const none=document.createElement('option');none.value='';
  none.textContent='(none — Site Manager & Mobility only)';sel.appendChild(none);
  for(const h of j.consoles){{const o=document.createElement('option');o.value=h.id;
    o.textContent=(h.name||h.id)+(h.type?(' — '+h.type):'');sel.appendChild(o);}}
  if(j.consoles.length===1)sel.value=j.consoles[0].id;
  if(!j.consoles.length)setErr('No consoles found for this account.');
}}
</script>
"""
    return _page(body)


def _result_page(base: str, client_id: str, client_secret: str) -> str:
    redirects = ", ".join(html.escape(u) for u in _redirect_uris())
    body = f"""
<h1>✅ Connection created</h1>
<p>In Claude, open <b>Settings → Connectors → Add custom connector</b> and enter:</p>
<div class="card">
  <div class="row"><b>MCP server URL</b><br><code>{html.escape(base)}/mcp</code></div>
  <div class="row"><b>OAuth client ID</b><br><code>{html.escape(client_id)}</code></div>
  <div class="row"><b>OAuth client secret</b><br><code>{html.escape(client_secret)}</code></div>
</div>
<p class="muted">Store the secret now — it is not shown again. Authorized
redirects: {redirects}.</p>
<p><a href="/">← Back to your connections</a></p>
"""
    return _page(body)


# ---------------------------------------------------------------------------
# Routes: passwordless accounts
# ---------------------------------------------------------------------------


@mcp.custom_route("/register", methods=["GET"])
async def register_get(request: Request) -> HTMLResponse:
    if _uid(request):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(_register_page())


@mcp.custom_route("/webauthn/register/begin", methods=["POST"])
async def register_begin(request: Request) -> JSONResponse:
    store = _store()
    if store is None:
        return JSONResponse({"error": "server misconfigured"}, status_code=500)
    body = await request.json()

    gate = os.environ.get("UNIFI_ONBOARD_CODE")
    if gate and str(body.get("code", "")) != gate:
        return JSONResponse({"error": "invalid invite code"}, status_code=403)

    email = str(body.get("email", "")).strip() or request.session.get("email", "")
    if not email:
        return JSONResponse({"error": "email required"}, status_code=400)

    options = generate_registration_options(
        rp_id=_rp_id(request),
        rp_name=_rp_name(),
        user_name=email,
        user_id=secrets.token_bytes(16),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    request.session["wa_challenge"] = bytes_to_base64url(options.challenge)
    request.session["wa_reg_email"] = email
    return JSONResponse(_json(options))


@mcp.custom_route("/webauthn/register/complete", methods=["POST"])
async def register_complete(request: Request) -> JSONResponse:
    store = _store()
    if store is None:
        return JSONResponse({"error": "server misconfigured"}, status_code=500)
    challenge = request.session.pop("wa_challenge", None)
    email = request.session.pop("wa_reg_email", None)
    if not challenge or not email:
        return JSONResponse({"error": "no registration in progress"}, status_code=400)

    body = await request.json()
    try:
        verification = verify_registration_response(
            credential=body["credential"],
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=_rp_id(request),
            expected_origin=_base_url(request),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Passkey registration failed: %s", e)
        return JSONResponse({"error": "verification failed"}, status_code=400)

    # New passkey signing in as the current user adds a credential; otherwise
    # it creates a fresh account.
    uid = _uid(request) or await store.create_admin(email)
    await store.add_credential(
        admin_id=uid,
        credential_id=bytes_to_base64url(verification.credential_id),
        public_key=bytes_to_base64url(verification.credential_public_key),
        sign_count=verification.sign_count,
    )
    request.session["uid"] = uid
    request.session["email"] = email
    logger.info("Registered passkey for user %s", email)
    return JSONResponse({"ok": True})


@mcp.custom_route("/login", methods=["GET"])
async def login_get(request: Request) -> HTMLResponse:
    if _uid(request):
        return RedirectResponse("/", status_code=303)
    store = _store()
    if store is None or not store.has_admin():
        return RedirectResponse("/register", status_code=303)
    return HTMLResponse(_login_page())


@mcp.custom_route("/webauthn/login/begin", methods=["POST"])
async def login_begin(request: Request) -> JSONResponse:
    store = _store()
    if store is None or not store.has_admin():
        return JSONResponse({"error": "no accounts yet"}, status_code=400)
    # Usernameless: let the authenticator offer any resident passkey for this RP.
    options = generate_authentication_options(
        rp_id=_rp_id(request),
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    request.session["wa_challenge"] = bytes_to_base64url(options.challenge)
    return JSONResponse(_json(options))


@mcp.custom_route("/webauthn/login/complete", methods=["POST"])
async def login_complete(request: Request) -> JSONResponse:
    store = _store()
    if store is None:
        return JSONResponse({"error": "server misconfigured"}, status_code=500)
    challenge = request.session.pop("wa_challenge", None)
    if not challenge:
        return JSONResponse({"error": "no login in progress"}, status_code=400)

    credential = (await request.json())["credential"]
    cred_rec = store.get_credential(credential.get("id", ""))
    if cred_rec is None:
        return JSONResponse({"error": "unknown passkey"}, status_code=400)
    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=_rp_id(request),
            expected_origin=_base_url(request),
            credential_public_key=base64url_to_bytes(cred_rec["public_key"]),
            credential_current_sign_count=cred_rec.get("sign_count", 0),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Passkey login failed: %s", e)
        return JSONResponse({"error": "verification failed"}, status_code=400)

    await store.update_sign_count(credential["id"], verification.new_sign_count)
    user = store.get_admin(cred_rec["admin_id"])
    request.session["uid"] = cred_rec["admin_id"]
    request.session["email"] = user["email"] if user else ""
    return JSONResponse({"ok": True})


@mcp.custom_route("/logout", methods=["GET"])
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------------------
# Routes: connections (per user)
# ---------------------------------------------------------------------------


@mcp.custom_route("/", methods=["GET"])
async def home(request: Request) -> HTMLResponse:
    uid = _uid(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)
    store = _store()
    tenants = store.list_tenants(owner_id=uid) if store else []
    return HTMLResponse(_dashboard_page(request.session.get("email", ""), tenants))


@mcp.custom_route("/onboard", methods=["POST"])
async def onboard_post(request: Request) -> HTMLResponse:
    uid = _uid(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)
    store = _store()
    if store is None:
        return HTMLResponse(_page("Server misconfigured."), status_code=500)

    form = await request.form()
    gate = os.environ.get("UNIFI_ONBOARD_CODE")
    email = request.session.get("email", "")
    if gate and str(form.get("onboard_code", "")) != gate:
        return HTMLResponse(
            _dashboard_page(email, store.list_tenants(owner_id=uid), "Invalid code."),
            status_code=403,
        )
    api_key = str(form.get("api_key", "")).strip()
    if not api_key:
        return HTMLResponse(
            _dashboard_page(
                email, store.list_tenants(owner_id=uid), "An API key is required."
            ),
            status_code=400,
        )
    console_id = str(form.get("console_id", "")).strip()
    label = str(form.get("label", "")).strip()

    tenant = await store.create_tenant(
        api_key=api_key,
        owner_id=uid,
        label=label,
        network_console_id=console_id,
        protect_console_id=console_id,
    )
    logger.info("User %s created connection %s (label=%r)", uid, tenant.tenant_id, label)
    return HTMLResponse(
        _result_page(_base_url(request), tenant.client_id, tenant.client_secret)
    )


@mcp.custom_route("/hosts", methods=["POST"])
async def list_account_hosts(request: Request) -> JSONResponse:
    """List the consoles an API key can reach (for the onboarding picker)."""
    if not _uid(request):
        return JSONResponse({"error": "sign in first"}, status_code=401)
    api_key = str((await request.json()).get("api_key", "")).strip()
    if not api_key:
        return JSONResponse({"error": "API key required"}, status_code=400)

    from unifi_mcp.client import UniFiApiError, UniFiClient

    client = UniFiClient(api_key=api_key)
    try:
        data = await client.list_hosts(page_size=200)
    except UniFiApiError as e:
        return JSONResponse(
            {"error": f"UniFi API error {e.status_code}: {e.message}"},
            status_code=400,
        )
    finally:
        await client.close()

    consoles = []
    for h in data.get("data", []):
        state = h.get("reportedState") or {}
        name = state.get("name") or state.get("hostname") or h.get("ipAddress") or ""
        consoles.append({"id": h.get("id"), "name": name, "type": h.get("type", "")})
    return JSONResponse({"consoles": consoles})


@mcp.custom_route("/connections/delete", methods=["POST"])
async def connection_delete(request: Request) -> RedirectResponse:
    uid = _uid(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)
    store = _store()
    form = await request.form()
    tenant_id = str(form.get("tenant_id", ""))
    if store and tenant_id:
        ok = await store.delete_tenant(tenant_id, owner_id=uid)
        logger.info("User %s revoked connection %s (ok=%s)", uid, tenant_id, ok)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# OAuth discovery metadata — request-derived so it works behind any host/proxy
# without configuration. Inserted ahead of the SDK's fixed-issuer routes.
# ---------------------------------------------------------------------------


async def oauth_authorization_server_metadata(request: Request) -> JSONResponse:
    base = _base_url(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_post"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": [SCOPE],
        }
    )


async def oauth_protected_resource_metadata(request: Request) -> JSONResponse:
    base = _base_url(request)
    return JSONResponse(
        {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
        }
    )


# ---------------------------------------------------------------------------
# ASGI app
# ---------------------------------------------------------------------------

app = mcp.streamable_http_app()

# Shadow the SDK's fixed-issuer metadata with request-derived versions (matched
# first because they're inserted at the front of the route list).
app.router.routes.insert(
    0,
    Route(
        "/.well-known/oauth-protected-resource",
        oauth_protected_resource_metadata,
        methods=["GET"],
    ),
)
app.router.routes.insert(
    0,
    Route(
        "/.well-known/oauth-authorization-server",
        oauth_authorization_server_metadata,
        methods=["GET"],
    ),
)

app.add_middleware(
    SessionMiddleware,
    secret_key=_SESSION_SECRET,
    session_cookie="unifi_session",
    same_site="lax",
    https_only=os.environ.get("UNIFI_PUBLIC_URL", "").startswith("https"),
)


def main() -> None:
    """Entry point: run the combined onboarding + MCP server over HTTP."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="UniFi MCP multi-tenant web server")
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("MCP_PORT", "8000"))
    )
    args = parser.parse_args()

    logger.info("Starting multi-user UniFi MCP on %s:%s", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
