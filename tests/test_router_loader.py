"""Contracts for modular FastAPI router discovery."""
from __future__ import annotations

from types import ModuleType, SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI

from api import router_loader


def _package(name: str) -> ModuleType:
    package = ModuleType(name)
    package.__path__ = []  # type: ignore[attr-defined]
    return package


def test_discovery_is_public_flat_and_deterministic(monkeypatch) -> None:
    package = _package("sample.routes")
    alpha = ModuleType("sample.routes.alpha")
    alpha.router = APIRouter(prefix="/alpha")  # type: ignore[attr-defined]
    zeta = ModuleType("sample.routes.zeta")
    zeta.router = APIRouter(prefix="/zeta")  # type: ignore[attr-defined]
    modules = {
        "sample.routes": package,
        "sample.routes.alpha": alpha,
        "sample.routes.zeta": zeta,
    }

    monkeypatch.setattr(
        router_loader.importlib,
        "import_module",
        lambda name: modules[name],
    )
    monkeypatch.setattr(
        router_loader.pkgutil,
        "iter_modules",
        lambda path, prefix: [
            SimpleNamespace(name=f"{prefix}zeta", ispkg=False),
            SimpleNamespace(name=f"{prefix}_private", ispkg=False),
            SimpleNamespace(name=f"{prefix}nested", ispkg=True),
            SimpleNamespace(name=f"{prefix}alpha", ispkg=False),
        ],
    )

    result = router_loader.discover_routers("sample.routes")

    assert [item.module_name for item in result] == [
        "sample.routes.alpha",
        "sample.routes.zeta",
    ]


def test_invalid_router_contract_is_rejected(monkeypatch) -> None:
    package = _package("invalid.routes")
    invalid = ModuleType("invalid.routes.broken")
    invalid.router = object()  # type: ignore[attr-defined]

    monkeypatch.setattr(
        router_loader.importlib,
        "import_module",
        lambda name: package if name == "invalid.routes" else invalid,
    )
    monkeypatch.setattr(
        router_loader.pkgutil,
        "iter_modules",
        lambda path, prefix: [
            SimpleNamespace(name=f"{prefix}broken", ispkg=False)
        ],
    )

    with pytest.raises(
        router_loader.RouterDiscoveryError,
        match="must be a fastapi.APIRouter",
    ):
        router_loader.discover_routers("invalid.routes")


def test_discovered_router_is_included(monkeypatch) -> None:
    router = APIRouter()

    @router.get("/contract-health")
    def contract_health() -> dict[str, str]:
        return {"status": "ok"}

    monkeypatch.setattr(
        router_loader,
        "discover_routers",
        lambda package_name: [
            router_loader.DiscoveredRouter(
                module_name="sample.routes.health",
                router=router,
            )
        ],
    )
    app = FastAPI()

    included = router_loader.include_discovered_routers(
        app,
        "sample.routes",
    )

    assert included == ["sample.routes.health"]
    assert any(route.path == "/contract-health" for route in app.routes)
