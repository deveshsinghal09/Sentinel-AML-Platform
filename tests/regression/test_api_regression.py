from __future__ import annotations

from fastapi import FastAPI

from api.router_loader import discover_routers, include_discovered_routers


def test_all_devesh_route_modules_are_discovered_deterministically():
    discovered = discover_routers()
    names = [item.module_name for item in discovered]

    assert names == sorted(names)
    assert {
        "api.routes.auth",
        "api.routes.evidence",
        "api.routes.governance",
        "api.routes.health",
        "api.routes.query",
        "api.routes.workflow",
    }.issubset(names)


def test_openapi_contract_has_no_duplicate_method_path_or_operation_id():
    app = FastAPI()
    include_discovered_routers(app)
    schema = app.openapi()

    operations: list[tuple[str, str, str]] = []
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            operations.append((method, path, operation["operationId"]))

    method_paths = [(method, path) for method, path, _ in operations]
    operation_ids = [operation_id for _, _, operation_id in operations]
    assert len(method_paths) == len(set(method_paths))
    assert len(operation_ids) == len(set(operation_ids))


def test_mutating_business_routes_publish_bounded_request_contracts():
    app = FastAPI()
    include_discovered_routers(app)
    schema = app.openapi()

    assign = schema["paths"]["/workflow/queue/{alert_id}/assign"]["post"]
    query = schema["paths"]["/query"]["post"]
    assert assign["requestBody"]["required"] is True
    assert query["requestBody"]["required"] is True
    assert "422" in assign["responses"]
    assert "422" in query["responses"]
