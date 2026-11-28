"""Check the documented Mac REST route inventory against its source owners."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNERS = ("api.py", "api_dock_routes.py", "api_memory_routes.py")
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _routes(source: str) -> set[tuple[str, str, str, int]]:
    routes = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (isinstance(func, ast.Attribute) and func.attr in METHODS
                    and isinstance(func.value, ast.Name) and func.value.id == "app"):
                continue
            kwargs = {item.arg: item.value for item in decorator.keywords}
            dependencies = kwargs["dependencies"]
            assert isinstance(dependencies, ast.List)
            auth = {dep.args[0].id for dep in dependencies.elts
                    if isinstance(dep, ast.Call) and dep.args
                    and isinstance(dep.args[0], ast.Name)} & {"operator", "authorize"}
            assert len(auth) == 1
            bearer = "operator" if "operator" in auth else "tool or operator"
            status = ast.literal_eval(kwargs.get("status_code", ast.Constant(200)))
            route = (func.attr.upper(), ast.literal_eval(decorator.args[0]), bearer, status)
            assert route not in routes
            routes.add(route)
    return routes


def test_mac_rest_route_inventory_matches_source():
    guide = (ROOT / "docs/guides/interfaces.md").read_text(encoding="utf-8")
    inventory = guide.split("<!-- mac-rest-inventory:start -->", 1)[1].split(
        "<!-- mac-rest-inventory:end -->", 1,
    )[0]
    rows = re.findall(
        r"^\| `(\w+) ([^`]+)` \| (operator|tool or operator) \| (\d+) \|",
        inventory, flags=re.MULTILINE,
    )
    documented = {(method, path, bearer, int(status)) for method, path, bearer, status in rows}
    assert len(documented) == len(rows), "Duplicate documented route"
    sources = ROOT / "code/laptop/src/desk_robot"
    actual = set().union(*(_routes((sources / name).read_text(encoding="utf-8"))
                           for name in OWNERS))
    assert documented == actual
