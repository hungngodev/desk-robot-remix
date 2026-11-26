"""Keep the selected host API signatures fully annotated without importing hardware."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "laptop" / "src" / "desk_robot"


def _assert_parameterized(annotation: ast.expr, location: str) -> None:
    generic_names = {"dict", "list", "tuple", "set", "frozenset", "Callable", "Awaitable",
                     "Task", "ndarray", "NDArray", "AsyncIterator"}
    nodes = list(ast.walk(annotation))
    parameterized = {node.value for node in nodes if isinstance(node, ast.Subscript)}
    for node in nodes:
        name = node.id if isinstance(node, ast.Name) else (
            node.attr if isinstance(node, ast.Attribute) else None
        )
        assert name not in generic_names or node in parameterized, (
            f"{location} unparameterized generic {name}"
        )


@pytest.mark.parametrize(
    "module", ["cli", "calibration", "aux", "live_turns", "live_voice_events", "api_lifecycle"],
)
def test_host_api_signature_annotations(module: str) -> None:
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    if module == "api_lifecycle":
        assert any(
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in tree.body
        ), f"{module} missing future annotations"
    functions = [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    for function in functions:
        assert function.returns is not None, f"{module}:{function.lineno} missing return type"
        _assert_parameterized(function.returns, f"{module}:{function.lineno} return")
        arguments = function.args
        parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        if arguments.vararg is not None:
            parameters.append(arguments.vararg)
        if arguments.kwarg is not None:
            parameters.append(arguments.kwarg)
        for parameter in parameters:
            if parameter.arg not in {"self", "cls"}:
                assert parameter.annotation is not None, (
                    f"{module}:{function.lineno} missing type for {parameter.arg}"
                )
                _assert_parameterized(
                    parameter.annotation, f"{module}:{function.lineno} {parameter.arg}"
                )
