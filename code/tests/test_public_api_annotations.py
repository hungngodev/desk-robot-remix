"""Keep the selected host API signatures fully annotated without importing hardware."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "laptop" / "src" / "desk_robot"


@pytest.mark.parametrize("module", ["cli", "calibration", "aux", "live_turns", "live_voice_events"])
def test_host_api_signature_annotations(module: str) -> None:
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    functions = [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    for function in functions:
        assert function.returns is not None, f"{module}:{function.lineno} missing return type"
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
