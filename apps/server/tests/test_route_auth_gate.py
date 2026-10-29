# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Structural auth gate: every mounted ``/api`` route must wire an
authentication dependency, or be listed in ``PUBLIC_ROUTES`` with a reason.

This is a *structural* check ("is a guard wired?"), not a *semantic* one
("does it actually reject?"). It exists to catch the "new router without auth"
class — a router added in ``app.main`` without a router-level scope guard and
without endpoint-level auth — at PR time instead of in production.

Why introspection works: a router-level ``Depends(require_scope(...))`` is as visible
as an endpoint-level ``Depends(get_current_admin)``. FastAPI <= 0.136 propagates
``include_router(dependencies=...)`` into each route's ``dependant.dependencies``; from 0.138 the
include keeps them in ``include_context.dependencies``, which we read for the router that holds
the route. We walk the recursive dependency tree of both and look for any known auth callable by
its ``module:qualname``.

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


def _qualname(call) -> str:
    # Class-based dependencies (HTTPBearer, ApiKeyOrUser instances) have no __qualname__.
    qualname = getattr(call, "__qualname__", None) or type(call).__qualname__
    module = getattr(call, "__module__", None) or type(call).__module__
    return f"{module}:{qualname}"


def _include_dependency_qualnames(path: str, app=None, route=None) -> set[str]:
    """The dependencies an include_router(..., dependencies=...) adds to the router that
    holds `path` (with `route`: that very route, as another router can hold the same path
    under another method), with their own sub-dependencies. FastAPI >= 0.138 keeps them on the
    include (_IncludedRouter.include_context), not in the route's dependant."""
    from fastapi.dependencies.utils import get_dependant

    if app is None:
        from app.main import app

    names: set[str] = set()

    def walk(dependant) -> None:
        for dep in dependant.dependencies:
            names.add(_qualname(dep.call))
            walk(dep)

    for node in app.routes:
        ctx = getattr(node, "include_context", None)
        routes = getattr(getattr(ctx, "included_router", None), "routes", None) or ()
        if any(
            (r is route) if route is not None else (getattr(r, "path", None) == path)
            for r in routes
        ):
            for depends in ctx.dependencies:
                call = depends.dependency
                names.add(_qualname(call))
                walk(get_dependant(path=path, call=call))
    return names


def _dependency_qualnames(route: APIRoute, app=None) -> set[str]:
    """All ``module:qualname`` strings in the route's recursive dependency tree, including
    the ones its router got from ``include_router(..., dependencies=...)``."""
    names: set[str] = set()

    def walk(deps) -> None:
        for dep in deps:
            names.add(_qualname(dep.call))
            walk(dep.dependencies)

    walk(route.dependant.dependencies)
    return names | _include_dependency_qualnames(route.path, app, route)


def _is_guarded(route: APIRoute, app=None) -> bool:
    return any(
        token in qualname
        for qualname in _dependency_qualnames(route, app)
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


def test_detector_sees_a_guard_that_only_the_include_carries():
    """A router without its own guard, included with ``dependencies=[Depends(guard)]``,
    is guarded; on FastAPI >= 0.138 the guard is not in the route's dependant."""
    from fastapi import APIRouter, Depends, FastAPI

    from app.core.auth import get_current_admin

    router = APIRouter()

    @router.get("/inner")
    def _inner():
        return {}

    bare = APIRouter()

    @bare.get("/bare")
    def _bare():
        return {}

    probe = FastAPI()
    probe.include_router(router, dependencies=[Depends(get_current_admin)])
    probe.include_router(bare)

    routes = {r.path: r for r in _collect_api_routes(probe)}
    assert set(routes) == {"/inner", "/bare"}
    assert _is_guarded(routes["/inner"], probe) is True
    assert _is_guarded(routes["/bare"], probe) is False


def test_detector_ties_an_include_guard_to_its_route_not_to_the_path():
    """The same path in two routers (GET guarded by its include, POST bare) must not lend the
    POST the GET's guard."""
    from fastapi import APIRouter, Depends, FastAPI

    from app.core.auth import get_current_admin

    guarded = APIRouter()

    @guarded.get("/x")
    def _get():
        return {}

    bare = APIRouter()

    @bare.post("/x")
    def _post():
        return {}

    probe = FastAPI()
    probe.include_router(guarded, dependencies=[Depends(get_current_admin)])
    probe.include_router(bare)

    routes = {next(iter(r.methods)): r for r in _collect_api_routes(probe)}
    assert _is_guarded(routes["GET"], probe) is True
    assert _is_guarded(routes["POST"], probe) is False
