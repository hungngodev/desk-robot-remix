"""Guard project-owned body firmware against explicit heap allocation regressions.

This is not a proof about allocations inside the Arduino or ESP-IDF drivers.
"""

import re
from pathlib import Path

import pytest

BODY = Path(__file__).resolve().parents[1] / "firmware" / "body"
RT_FILES = (
    "lib/BodyControl/BodyControl.cpp",
    "lib/BodyControl/BodyControl.h",
    "lib/CliffGuard/CliffGuard.cpp",
    "lib/CliffGuard/CliffGuard.h",
    "lib/TofBus/TofBus.cpp",
    "lib/TofBus/TofBus.h",
    "lib/StepperDrive/StepperDrive.cpp",
    "lib/StepperDrive/StepperDrive.h",
    "src/main.cpp",
)

# Match comments and ordinary literals first, so prose and protocol payloads
# cannot create false positives. This is a narrow source guard, not a C++ parser.
TOKENS = re.compile(
    r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    r"|(?P<heap>\b(?:new|String|malloc|calloc|realloc|strdup|strndup|"
    r"pvPortMalloc|heap_caps_\w*alloc|asprintf|vasprintf)\b"
    r"|\bstd\s*::\s*(?:vector|basic_string|string|deque|list|map|"
    r"unordered_map|make_unique|make_shared)\b)"
)


def explicit_heap_tokens(source: str) -> list[tuple[int, str]]:
    return [
        (source.count("\n", 0, match.start()) + 1, match.group("heap"))
        for match in TOKENS.finditer(source)
        if match.group("heap") is not None
    ]


@pytest.mark.parametrize("relative_path", RT_FILES)
def test_body_rt_source_avoids_explicit_heap(relative_path: str) -> None:
    source = (BODY / relative_path).read_text(encoding="utf-8")
    violations = explicit_heap_tokens(source)
    assert not violations, f"{relative_path}: {violations}"


@pytest.mark.parametrize(
    ("allocation", "token"),
    [
        ("new int", "new"),
        ("String message", "String"),
        ("std :: vector<int> buffer", "std :: vector"),
        ("malloc(8)", "malloc"),
        ("heap_caps_malloc(8, 0)", "heap_caps_malloc"),
        ("std::make_unique<int>()", "std::make_unique"),
    ],
)
def test_heap_guard_detects_mutations(allocation: str, token: str) -> None:
    source = f'// {allocation}\nconst char* label = "{allocation}";\n{allocation};'
    assert explicit_heap_tokens(source) == [(3, token)]
