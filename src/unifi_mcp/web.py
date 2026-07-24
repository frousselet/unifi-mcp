"""Multi-tenant onboarding web app + combined ASGI server (passwordless).

Running ``unifi-mcp-web`` serves, on a single port:

- ``GET /``            → onboarding form (admin only)
- ``POST /onboard``    → creates a tenant → MCP URL + OAuth client id/secret
- ``/setup``           → first-run: register the first admin passkey
- ``/login``           → sign in with a passkey
- ``/admin``           → list/delete tenant connections
- ``/mcp``             → the shared, OAuth-protected MCP endpoint
- ``/authorize`` ``/token`` ``/.well-known/oauth-*`` → OAuth 2.1 server

Admin authentication is **passwordless (WebAuthn passkeys only)**. There is no
default account: on first run the UI invites you to create one. Tenant UniFi
keys and OAuth client secrets are encrypted at rest; OAuth tokens are hashed.
"""

from __future__ import annotations

import html
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
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from unifi_mcp import server  # noqa: E402
from unifi_mcp.oauth import _redirect_uris  # noqa: E402

logger = logging.getLogger("unifi-mcp.web")

mcp = server.mcp

# Session signing key for the admin browser cookie (WebAuthn challenges + login).
_SESSION_SECRET = os.environ.get("UNIFI_SECRET_KEY") or secrets.token_urlsafe(32)


def _public_url() -> str:
    return os.environ.get("UNIFI_PUBLIC_URL", "http://localhost:8000").rstrip("/")


def _rp_id() -> str:
    return urlparse(_public_url()).hostname or "localhost"


def _rp_name() -> str:
    return os.environ.get("UNIFI_RP_NAME", "UniFi MCP")


def _is_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))


def _store():
    return server.STORE


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UniFi MCP</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 3rem auto;
         padding: 0 1rem; line-height: 1.5; }}
  h1 {{ font-size: 1.5rem; }}
  label {{ display:block; margin-top: 1rem; font-weight: 600; }}
  input {{ width: 100%; padding: .6rem; margin-top: .3rem; box-sizing: border-box;
          border: 1px solid #8888; border-radius: 6px; font-size: 1rem;
          background: transparent; color: inherit; }}
  small {{ color: #888; font-weight: 400; }}
  button {{ margin-top: 1.5rem; padding: .7rem 1.2rem; font-size: 1rem;
           border-radius: 6px; border: 0; background: #2d6cdf; color: #fff;
           cursor: pointer; }}
  .card {{ border: 1px solid #8884; border-radius: 10px; padding: 1.2rem 1.4rem; }}
  code {{ background: #8882; padding: .15rem .4rem; border-radius: 4px;
         word-break: break-all; }}
  .row {{ margin: .8rem 0; }}
  .muted {{ color:#888; font-size:.9rem; }}
  .err {{ color:#c0392b; }}
  table {{ width:100%; border-collapse:collapse; }}
  th, td {{ text-align:left; padding:.4rem .3rem; border-bottom:1px solid #8883; }}
</style></head><body>
{body}
</body></html>"""

# Minimal vanilla WebAuthn helper shared by setup + login pages.
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

async function doRegister(email){
 setErr('');
 const opts=await postJSON('/webauthn/register/begin',{email});
 opts.challenge=b64urlToBuf(opts.challenge);
 opts.user.id=b64urlToBuf(opts.user.id);
 if(opts.excludeCredentials)for(const c of opts.excludeCredentials)c.id=b64urlToBuf(c.id);
 const cred=await navigator.credentials.create({publicKey:opts});
 const payload={id:cred.id,rawId:bufToB64url(cred.rawId),type:cred.type,
  clientExtensionResults:cred.getClientExtensionResults?cred.getClientExtensionResults():{},
  response:{clientDataJSON:bufToB64url(cred.response.clientDataJSON),
   attestationObject:bufToB64url(cred.response.attestationObject),
   transports:cred.response.getTransports?cred.response.getTransports():[]}};
 await postJSON('/webauthn/register/complete',{credential:payload});
 location.href='/admin';
}

async function doLogin(){
 setErr('');
 const opts=await postJSON('/webauthn/login/begin',{});
 opts.challenge=b64urlToBuf(opts.challenge);
 if(opts.allowCredentials)for(const c of opts.allowCredentials)c.id=b64urlToBuf(c.id);
 const cred=await navigator.credentials.get({publicKey:opts});
 const r=cred.response;
 const payload={id:cred.id,rawId:bufToB64url(cred.rawId),type:cred.type,
  clientExtensionResults:cred.getClientExtensionResults?cred.getClientExtensionResults():{},
  response:{clientDataJSON:bufToB64url(r.clientDataJSON),
   authenticatorData:bufToB64url(r.authenticatorData),
   signature:bufToB64url(r.signature),
   userHandle:r.userHandle?bufToB64url(r.userHandle):null}};
 await postJSON('/webauthn/login/complete',{credential:payload});
 location.href='/admin';
}
</script>
"""


def _page(body: str) -> str:
    return _PAGE.format(body=body)


def _setup_page() -> str:
    body = f"""
<h1>Create the first admin</h1>
<p class="muted">This service is passwordless. Register a passkey (Touch ID,
Windows Hello, a security key, or your phone) to secure the admin area.</p>
<p id="err" class="err"></p>
<div class="card">
  <label>Admin email<input id="email" type="email" required
         placeholder="you@example.com"></label>
  <button onclick="const e=document.getElementById('email').value.trim();
          if(!e){{setErr('Enter an email.');return;}}
          doRegister(e).catch(x=>setErr(x.message))">Create passkey</button>
</div>
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
{_WEBAUTHN_JS}
"""
    return _page(body)


def _onboard_form(error: str = "") -> str:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    gate = ""
    if os.environ.get("UNIFI_ONBOARD_CODE"):
        gate = (
            '<label>Onboarding code<input name="onboard_code" required '
            'autocomplete="off"></label>'
        )
    body = f"""
<h1>New connection <a href="/admin" style="float:right;font-size:.9rem">Dashboard</a></h1>
<p class="muted">Enter a UniFi cloud API key (create one at
<a href="https://unifi.ui.com">unifi.ui.com → API</a>). You'll get an MCP URL and
OAuth credentials for Claude's custom-connector dialog.</p>
{err}
<form method="post" action="/onboard" class="card">
  {gate}
  <label>UniFi API key <small>(required)</small>
    <input name="api_key" required autocomplete="off" placeholder="0HMN…XvWC"></label>
  <label>Console ID <small>(optional — enables Network &amp; Protect tools)</small>
    <input name="console_id" autocomplete="off" placeholder="900A6F…:123456789"></label>
  <label>Label <small>(optional)</small>
    <input name="label" autocomplete="off" placeholder="Home network"></label>
  <button type="submit">Create connection</button>
</form>
"""
    return _page(body)


def _result_page(url: str, client_id: str, client_secret: str) -> str:
    redirects = ", ".join(html.escape(u) for u in _redirect_uris())
    body = f"""
<h1>✅ Connection created</h1>
<p>In Claude, open <b>Settings → Connectors → Add custom connector</b> and enter:</p>
<div class="card">
  <div class="row"><b>MCP server URL</b><br><code>{html.escape(url)}/mcp</code></div>
  <div class="row"><b>OAuth client ID</b><br><code>{html.escape(client_id)}</code></div>
  <div class="row"><b>OAuth client secret</b><br><code>{html.escape(client_secret)}</code></div>
</div>
<p class="muted">Store the secret now — it is not shown again. Authorized
redirects: {redirects}.</p>
<p><a href="/">← New connection</a> · <a href="/admin">Dashboard</a></p>
"""
    return _page(body)


def _dashboard_page(tenants: list[dict]) -> str:
    if tenants:
        rows = "".join(
            f"<tr><td>{html.escape(t['label'] or '—')}</td>"
            f"<td><code>{html.escape(t['client_id'])}</code></td>"
            f"<td><code>{html.escape(t['network_console_id'] or '—')}</code></td>"
            f'<td><form method="post" action="/admin/delete" style="margin:0" '
            f"onsubmit=\"return confirm('Delete this connection?')\">"
            f'<input type="hidden" name="tenant_id" value="{html.escape(t["tenant_id"])}">'
            f'<button style="background:#c0392b;margin:0;padding:.3rem .6rem">Delete</button>'
            f"</form></td></tr>"
            for t in tenants
        )
        table = (
            "<table><tr><th>Label</th><th>Client ID</th><th>Console</th><th></th></tr>"
            + rows
            + "</table>"
        )
    else:
        table = "<p class='muted'>No connections yet.</p>"
    body = f"""
<h1>Connections <a href="/logout" style="float:right;font-size:.9rem">Sign out</a></h1>
<p><a href="/">+ New connection</a></p>
<div class="card">{table}</div>
"""
    return _page(body)


# ---------------------------------------------------------------------------
# Routes: admin passkey auth
# ---------------------------------------------------------------------------


@mcp.custom_route("/setup", methods=["GET"])
async def setup_get(request: Request) -> HTMLResponse:
    store = _store()
    if store and store.has_admin() and not _is_admin(request):
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(_setup_page())


@mcp.custom_route("/webauthn/register/begin", methods=["POST"])
async def register_begin(request: Request) -> JSONResponse:
    store = _store()
    if store is None:
        return JSONResponse({"error": "server misconfigured"}, status_code=500)
    # Registration is allowed to bootstrap the first admin, or for a signed-in
    # admin adding another passkey.
    if store.has_admin() and not _is_admin(request):
        return JSONResponse({"error": "admin already configured"}, status_code=403)

    body = await request.json()
    email = str(body.get("email", "")).strip() or request.session.get("admin", "")
    if not email:
        return JSONResponse({"error": "email required"}, status_code=400)

    user_id = secrets.token_bytes(16)
    options = generate_registration_options(
        rp_id=_rp_id(),
        rp_name=_rp_name(),
        user_name=email,
        user_id=user_id,
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
    if store.has_admin() and not _is_admin(request):
        return JSONResponse({"error": "admin already configured"}, status_code=403)

    body = await request.json()
    try:
        verification = verify_registration_response(
            credential=body["credential"],
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=_rp_id(),
            expected_origin=_public_url(),
        )
    except Exception as e:  # noqa: BLE001 - surface verification failures
        logger.warning("Passkey registration failed: %s", e)
        return JSONResponse({"error": "verification failed"}, status_code=400)

    admin_id = request.session.get("admin_id")
    if not admin_id:
        admin_id = await store.create_admin(email)
    await store.add_credential(
        admin_id=admin_id,
        credential_id=bytes_to_base64url(verification.credential_id),
        public_key=bytes_to_base64url(verification.credential_public_key),
        sign_count=verification.sign_count,
    )
    request.session["admin"] = email
    request.session["admin_id"] = admin_id
    logger.info("Registered passkey for admin %s", email)
    return JSONResponse({"ok": True})


@mcp.custom_route("/login", methods=["GET"])
async def login_get(request: Request) -> HTMLResponse:
    store = _store()
    if _is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    if store is None or not store.has_admin():
        return RedirectResponse("/setup", status_code=303)
    return HTMLResponse(_login_page())


@mcp.custom_route("/webauthn/login/begin", methods=["POST"])
async def login_begin(request: Request) -> JSONResponse:
    store = _store()
    if store is None or not store.has_admin():
        return JSONResponse({"error": "no admin configured"}, status_code=400)
    allow = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(cid))
        for cid in store.list_credential_ids()
    ]
    options = generate_authentication_options(
        rp_id=_rp_id(),
        allow_credentials=allow or None,
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

    body = await request.json()
    credential = body["credential"]
    cred_rec = store.get_credential(credential.get("id", ""))
    if cred_rec is None:
        return JSONResponse({"error": "unknown passkey"}, status_code=400)

    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=_rp_id(),
            expected_origin=_public_url(),
            credential_public_key=base64url_to_bytes(cred_rec["public_key"]),
            credential_current_sign_count=cred_rec.get("sign_count", 0),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Passkey login failed: %s", e)
        return JSONResponse({"error": "verification failed"}, status_code=400)

    await store.update_sign_count(credential["id"], verification.new_sign_count)
    admin = store.get_admin(cred_rec["admin_id"])
    request.session["admin"] = admin["email"] if admin else "admin"
    request.session["admin_id"] = cred_rec["admin_id"]
    return JSONResponse({"ok": True})


@mcp.custom_route("/logout", methods=["GET"])
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------------------
# Routes: onboarding + dashboard (admin only)
# ---------------------------------------------------------------------------


def _require_admin(request: Request) -> RedirectResponse | None:
    if _is_admin(request):
        return None
    store = _store()
    if store is None or not store.has_admin():
        return RedirectResponse("/setup", status_code=303)
    return RedirectResponse("/login", status_code=303)


@mcp.custom_route("/", methods=["GET"])
async def home(request: Request) -> HTMLResponse:
    redirect = _require_admin(request)
    if redirect:
        return redirect
    return HTMLResponse(_onboard_form())


@mcp.custom_route("/onboard", methods=["GET"])
async def onboard_get(request: Request) -> RedirectResponse:  # noqa: ARG001
    return RedirectResponse("/", status_code=303)


@mcp.custom_route("/onboard", methods=["POST"])
async def onboard_post(request: Request) -> HTMLResponse:
    redirect = _require_admin(request)
    if redirect:
        return redirect
    form = await request.form()

    expected = os.environ.get("UNIFI_ONBOARD_CODE")
    if expected and str(form.get("onboard_code", "")) != expected:
        return HTMLResponse(_onboard_form("Invalid onboarding code."), status_code=403)

    api_key = str(form.get("api_key", "")).strip()
    if not api_key:
        return HTMLResponse(_onboard_form("An API key is required."), status_code=400)

    console_id = str(form.get("console_id", "")).strip()
    label = str(form.get("label", "")).strip()

    store = _store()
    if store is None:
        return HTMLResponse(_onboard_form("Server misconfigured."), status_code=500)

    tenant = await store.create_tenant(
        api_key=api_key,
        label=label,
        network_console_id=console_id,
        protect_console_id=console_id,
    )
    logger.info("Onboarded tenant %s (label=%r)", tenant.tenant_id, label)
    return HTMLResponse(
        _result_page(_public_url(), tenant.client_id, tenant.client_secret)
    )


@mcp.custom_route("/admin", methods=["GET"])
async def admin_dashboard(request: Request) -> HTMLResponse:
    redirect = _require_admin(request)
    if redirect:
        return redirect
    store = _store()
    return HTMLResponse(_dashboard_page(store.list_tenants() if store else []))


@mcp.custom_route("/admin/delete", methods=["POST"])
async def admin_delete(request: Request) -> RedirectResponse:
    redirect = _require_admin(request)
    if redirect:
        return redirect
    form = await request.form()
    tenant_id = str(form.get("tenant_id", ""))
    store = _store()
    if store and tenant_id:
        await store.delete_tenant(tenant_id)
        logger.info("Admin deleted tenant %s", tenant_id)
    return RedirectResponse("/admin", status_code=303)


def _json(options) -> dict:
    """Serialize py_webauthn options to a plain dict for the browser."""
    import json as _jsonmod

    return _jsonmod.loads(options_to_json(options))


# ---------------------------------------------------------------------------
# ASGI app
# ---------------------------------------------------------------------------

app = mcp.streamable_http_app()
app.add_middleware(
    SessionMiddleware,
    secret_key=_SESSION_SECRET,
    session_cookie="unifi_admin",
    same_site="lax",
    https_only=_public_url().startswith("https"),
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

    logger.info(
        "Starting multi-tenant UniFi MCP on %s:%s (public URL: %s, rp_id: %s)",
        args.host,
        args.port,
        _public_url(),
        _rp_id(),
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
