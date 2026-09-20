"""Discover trusted FastAPI routers from a package namespace."""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from types import ModuleType

from fastapi import APIRouter, FastAPI


class RouterDiscoveryError(RuntimeError):
    """Raised when an internal route module violates the router contract."""


@dataclass(frozen=True)
class DiscoveredRouter:
    """A validated router and the module that declared it."""

    module_name: str
    router: APIRouter


def _route_package(package_name: str) -> ModuleType:
    package = importlib.import_module(package_name)
    if not hasattr(package, "__path__"):
        raise RouterDiscoveryError(
            f"Route namespace {package_name!r} is not a package"
        )
    return package


def discover_routers(package_name: str = "api.routes") -> list[DiscoveredRouter]:
    """Return public route modules exposing exactly one ``APIRouter``.

    Discovery is deterministic and restricted to the configured internal
    package. Private modules and nested packages are not imported.
    """
    package = _route_package(package_name)
    prefix = f"{package_name}."
    modules = sorted(
        (
            item
            for item in pkgutil.iter_modules(package.__path__, prefix=prefix)
            if not item.ispkg
            and not item.name.rsplit(".", maxsplit=1)[-1].startswith("_")
        ),
        key=lambda item: item.name,
    )

    discovered: list[DiscoveredRouter] = []
    seen: set[int] = set()
    for item in modules:
        module = importlib.import_module(item.name)
        router = getattr(module, "router", None)
        if router is None:
            continue
        if not isinstance(router, APIRouter):
            raise RouterDiscoveryError(
                f"{item.name}.router must be a fastapi.APIRouter"
            )
        identity = id(router)
        if identity in seen:
            raise RouterDiscoveryError(
                f"{item.name} reuses a router declared by another module"
            )
        seen.add(identity)
        discovered.append(
            DiscoveredRouter(module_name=item.name, router=router)
        )
    return discovered


def include_discovered_routers(
    app: FastAPI,
    package_name: str = "api.routes",
) -> list[str]:
    """Attach discovered routers and return their module names."""
    discovered = discover_routers(package_name)
    for item in discovered:
        app.include_router(item.router)
    return [item.module_name for item in discovered]
