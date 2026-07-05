# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Structural auth gate: every mounted ``/api`` route must wire an
authentication dependency, or be listed in ``PUBLIC_ROUTES`` with a reason.

This is a *structural* check ("is a guard wired?"), not a *semantic* one
("does it actually reject?"). It exists to catch the "new router without auth"
class — a router added in ``app.main`` without a router-level scope guard and
without endpoint-level auth — at PR time instead of in production.

Why introspection works: FastAPI propagates ``include_router(dependencies=...)``
down into every route, so a router-level ``Depends(require_scope(...))`` shows
up in that route's ``dependant.dependencies`` tree just like an endpoint-level
``Depends(get_current_admin)`` does. We therefore walk the recursive dependency
tree and look for any known auth callable by its ``module:qualname``.

Adding a genuinely public route is a deliberate act: the test forces a line in
``PUBLIC_ROUTES`` (with a reason), rather than letting an unguarded route slip
in silently.
"""

from fastapi.routing import APIRoute

# Substrings of an auth dependency's ``module:qualname``. A route counts as
# guarded if ANY dependency anywhere in its recursive tree matches one of these.
#   require_scope   -> app.core.identity, mTLS scope guard (router-level)
#   get_current_user / get_current_admin -> app.core.auth, JWT bearer
#   ApiKeyOrUser    -> app.core.auth, API key or JWT
#   require_internal_key -> app.modules.notifications.router, shared-secret
#                           service-to-service ingress (monitoring -> server)
# Matched as substrings (not exact) so the inner closure name of
# ``require_scope`` (``require_scope.<locals>.dependency``) stays robust against
# trivial renames.
_AUTH_MARKER_TOKENS = (
    "require_scope",
    "get_current_user",
    "get_current_admin",
    "ApiKeyOrUser",
    "require_internal_key",
    # SSE stream: a short-lived-session bearer-JWT check (not get_current_user,
    # to avoid holding a DB connection for the stream's whole lifetime).
    "authenticate_stream_user",
)

# Deliberately public routes. Each entry is a conscious decision with a reason;
# keep this list short. (method, path) granularity so a public GET cannot
# silently open a sibling POST on the same path.
_PUBLIC_ROUTES = {
    ("POST", "/api/auth/login"),  # credential exchange, pre-auth
    ("POST", "/api/auth/refresh"),  # rotates session via HttpOnly cookie
    ("POST", "/api/auth/logout"),  # clears the refresh cookie
    ("POST", "/api/auth/bootstrap"),  # first-admin, one-time token in body
    ("POST", "/api/hooks/trigger/{token}"),  # public webhook, token in path
    ("POST", "/api/hooks/trigger"),  # public webhook, token in X-Hook-Token header (3.101)
    # agent activation, one-time provision token in body (no cert/JWT yet)
    ("POST", "/api/servers/{server_id}/provision/activate"),
}


def _dependency_qualnames(route: APIRoute) -> set[str]:
    """All ``module:qualname`` strings in the route's recursive dependency tree."""
    names: set[str] = set()

    def walk(deps) -> None:
        for dep in deps:
            call = dep.call
            qualname = getattr(call, "__qualname__", None) or type(call).__qualname__
            module = getattr(call, "__module__", None) or type(call).__module__
            names.add(f"{module}:{qualname}")
            walk(dep.dependencies)

    walk(route.dependant.dependencies)
    return names


def _is_guarded(route: APIRoute) -> bool:
    return any(
        token in qualname
        for qualname in _dependency_qualnames(route)
        for token in _AUTH_MARKER_TOKENS
    )


def _collect_api_routes(app) -> list[APIRoute]:
    """Every APIRoute under the app, collected recursively.

    Robust to how the *installed* FastAPI exposes included routers — the gate
    must not depend on a FastAPI internal that changes between versions:

    * FastAPI <= 0.136 flattens ``include_router`` straight into ``app.routes``
      as plain APIRoute objects.
    * FastAPI >= 0.138 wraps each included router in an opaque ``_IncludedRouter``
      that has *no* ``.routes``; its sub-routes live behind
      ``include_context.included_router.routes`` (full paths, prefix baked in).

    We descend through whichever shape a node exposes. Anything still unhandled
    is surfaced by the emptiness guard in the tests below, never silently
    dropped — a blind gate is worse than a red one.
    """
    collected: list[APIRoute] = []

    def descend(node) -> None:
        if isinstance(node, APIRoute):
            collected.append(node)
            return
        # Container (Mount / APIRouter / FastAPI's _IncludedRouter): prefer the
        # public ``.routes``, fall back to the >= 0.138 included-router shape.
        sub = getattr(node, "routes", None)
        if not sub:
            ctx = getattr(node, "include_context", None)
            included = getattr(ctx, "included_router", None)
            sub = getattr(included, "routes", None)
        for child in sub or ():
            descend(child)

    for route in app.routes:
        descend(route)
    return collected


def _api_methods(routes: list[APIRoute]):
    """Yield ``(method, path, route)`` for every ``/api`` route, sans HEAD/OPTIONS."""
    for route in routes:
        if not route.path.startswith("/api"):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, route.path, route


def test_every_api_route_is_guarded_or_explicitly_public():
    """Fail if any /api route lacks an auth dependency and isn't allowlisted."""
    from app.main import app

    api = list(_api_methods(_collect_api_routes(app)))
    # Emptiness guard: if route introspection ever collects nothing (e.g. a
    # future FastAPI reshuffle the walker doesn't understand), fail loudly here
    # instead of passing vacuously with an inert auth gate.
    assert api, (
        "introspection collected ZERO /api routes — _collect_api_routes no longer "
        "understands this FastAPI version's app.routes structure. The gate is "
        "blind until it's fixed."
    )

    offenders: list[str] = []
    for method, path, route in api:
        if (method, path) in _PUBLIC_ROUTES:
            continue
        if _is_guarded(route):
            continue
        offenders.append(f"{method} {path}")

    assert not offenders, (
        "These /api routes have no auth dependency and are not in the public "
        "allowlist:\n  "
        + "\n  ".join(sorted(offenders))
        + "\n\nWire a guard (router-level Depends(require_scope(...)) or an "
        "endpoint-level auth dependency), or — if the route is intentionally "
        "public — add (METHOD, PATH) to _PUBLIC_ROUTES with a reason."
    )


def test_allowlist_has_no_stale_entries():
    """Every _PUBLIC_ROUTES entry must still resolve to a real, unguarded route.

    Keeps the allowlist honest: if a route is removed or later gains a guard,
    its allowlist line should go too, instead of lingering as dead config that
    could mask a future regression on a re-used path.
    """
    from app.main import app

    live = {(method, path): route for method, path, route in _api_methods(_collect_api_routes(app))}

    stale: list[str] = []
    for method, path in _PUBLIC_ROUTES:
        route = live.get((method, path))
        if route is None:
            stale.append(f"{method} {path} (route no longer exists)")
        elif _is_guarded(route):
            stale.append(f"{method} {path} (now guarded — drop from allowlist)")

    assert not stale, "Stale _PUBLIC_ROUTES entries:\n  " + "\n  ".join(sorted(stale))


def test_detector_distinguishes_guarded_from_unguarded():
    """Anti-vacuous check: the detector must actually flag an unguarded route.

    Guards against the gate silently passing because introspection broke (e.g. a
    FastAPI internals change) and every route looks 'guarded' or has no
    dependencies at all.
    """
    from fastapi import Depends, FastAPI

    from app.core.auth import get_current_admin

    probe = FastAPI()

    @probe.get("/open")
    def _open():  # no auth dependency
        return {}

    @probe.get("/closed", dependencies=[Depends(get_current_admin)])
    def _closed():
        return {}

    routes = {r.path: r for r in probe.routes if isinstance(r, APIRoute)}
    assert _is_guarded(routes["/closed"]) is True
    assert _is_guarded(routes["/open"]) is False
