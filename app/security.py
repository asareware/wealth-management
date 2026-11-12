"""Request checks that run before any route: who is signed in, and whether a write is genuine.

1. Sign-in (second lock behind Entra ID)
   On App Service, "App Service Authentication" (often called Easy Auth) signs you in with
   Entra ID before a request ever reaches this app, then adds headers naming the user:
     X-MS-CLIENT-PRINCIPAL-ID    your Entra ID object ID (a GUID)
     X-MS-CLIENT-PRINCIPAL-NAME  your sign-in name (usually your email)
   App Service replaces any copies of these headers a browser tries to send itself.
   This check refuses requests with no signed-in user, and users not in ALLOWED_USERS, so a
   misconfigured sign-in setting (for example, "allow anyone in the tenant") still can't expose
   your data. The allow-list should hold your object ID: an email can be guessed, a GUID can't.
   Limit: if App Service Authentication were turned off entirely, these headers could be forged
   by someone who knew your object ID. Easy Auth must stay on; the Bicep template enforces it.

2. Cross-site request forgery (CSRF)
   Once you are signed in, your browser sends the sign-in cookie with every request to the
   site, including ones triggered by another website you visit. A browser will not let another
   site attach a custom header to a request, so every write (POST, PUT, PATCH, DELETE) to /api
   must carry X-Wealth-Portal: 1, which only the dashboard's own JavaScript sends.
"""
from fastapi import Request
from fastapi.responses import JSONResponse

from . import config

PUBLIC_PATHS = {"/healthz"}  # App Service's health check calls this without signing in
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-wealth-portal"


def signed_in_user(request: Request) -> dict | None:
    oid = request.headers.get("x-ms-client-principal-id", "").strip()
    name = request.headers.get("x-ms-client-principal-name", "").strip()
    return {"id": oid, "name": name} if (oid or name) else None


def is_allowed(user: dict) -> bool:
    if not config.ALLOWED_USERS:
        return False  # fail closed: an empty allow-list lets nobody in
    return user["id"].lower() in config.ALLOWED_USERS or user["name"].lower() in config.ALLOWED_USERS


def check(request: Request) -> JSONResponse | None:
    """Return a response to send instead of running the route, or None to let it through."""
    path = request.url.path
    if path in PUBLIC_PATHS:
        return None

    request.state.user = None
    if config.REQUIRE_SIGN_IN:
        user = signed_in_user(request)
        if user is None:
            return JSONResponse({"detail": "Sign-in required."}, status_code=401)
        if not is_allowed(user):
            msg = ("This account isn't allowed to use this portal." if config.ALLOWED_USERS
                   else "No users are allowed yet: set ALLOWED_USERS in the app settings.")
            return JSONResponse({"detail": msg}, status_code=403)
        request.state.user = user

    if request.method in WRITE_METHODS and path.startswith("/api/") and request.headers.get(CSRF_HEADER) != "1":
        return JSONResponse({"detail": "Request blocked: missing the portal's request header (CSRF check)."},
                            status_code=403)
    return None
