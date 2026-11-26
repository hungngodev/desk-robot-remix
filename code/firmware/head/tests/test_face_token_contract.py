"""Keep the model prompt, wire decoder and OLED glyph mapping in agreement."""

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]
CODE = HEAD.parents[1]
MODEL_MOODS = {"neutral", "happy", "thinking", "surprised"}
HSM_GLYPHS = {
    "kNeutral": "neutral",
    "kSmile": "happy",
    "kAngry": "angry",
    "kSad": "sad",
    "kSleepy": "sleepy",
    "kDoubt": "thinking",
    "kSurprised": "surprised",
}


def test_prompt_and_mac_allowlist_match():
    mac = CODE / "laptop/src/desk_robot"
    policy = ast.parse((mac / "expression_policy.py").read_text())
    allowed = next(
        node.value.args[0] for node in policy.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_MODEL_MOODS" for t in node.targets)
    )
    assert ast.literal_eval(allowed) == MODEL_MOODS
    pet = ast.parse((mac / "pet.py").read_text())
    prompts = [
        node.value for node in ast.walk(pet)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and "An optional OLED mood may be" in node.value
    ]
    assert len(prompts) == 1
    names = prompts[0].split("An optional OLED mood may be ", 1)[1].split(".", 1)[0]
    assert set(re.findall(r"\b[a-z]+\b", names)) == MODEL_MOODS | {"none", "or"}


def test_native_mood_roundtrip(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("Native C++ compiler unavailable")
    overlay = HEAD / "overlay"
    behavior = (overlay / "stackchan_behavior.hpp").read_text()
    board = (HEAD / "sense/desk_robot_sense.cc").read_text()
    enum = re.search(r"enum class Mood\s*:[^\{]+\{[^}]+\};", behavior).group()
    assert set(re.findall(r"\bk[A-Z]\w+", enum)) == HSM_GLYPHS.keys()
    mappings = [
        re.search(rf"static const char\* {name}\([^\n]+\{{.*?\n    \}}", board, re.S).group()
        for name in ("MoodName", "CosmeticMoodName")
    ]
    cases = "\n".join(
        f'assert(std::string_view(MoodName(Mood::{key})) == "{value}");'
        for key, value in HSM_GLYPHS.items()
    )
    wire = "\n".join(
        f'check("mood:{name}", "{name}");' for name in sorted(MODEL_MOODS)
    )
    source = tmp_path / "face_tokens.cc"
    binary = tmp_path / "face_tokens"
    source.write_text(
        '#include "robot_protocol.h"\n#include <cassert>\n#include <stdint.h>\n'
        '#include <initializer_list>\n'
        + "namespace stackchan::behavior {\n" + enum + "\n}\n"
        + "\n".join(mappings) + "\n"
        + """
using stackchan::behavior::Mood;
using namespace desk_robot;
static void check(std::string_view token, std::string_view glyph) {
    const auto mood = ParseCosmeticMood(token);
    assert(mood != CosmeticMood::kNone);
    CosmeticMoodCue cue;
    cue.offer(mood, 100U);
    const auto received = cue.take(108U);
    assert(received == mood);
    assert(std::string_view(CosmeticMoodName(received)) == glyph);
    assert(cue.take(108U) == CosmeticMood::kNone);
}
int main() {
""" + cases + "\n" + wire + "\n"
        + """
    for (auto token : {"mood:none", "mood:Happy", "mood:suprised", "mood:angry",
                       "mood:happy ", "happy", ""}) {
        assert(ParseCosmeticMood(token) == CosmeticMood::kNone);
    }
}
"""
    )
    pie = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", *pie, "-I", str(overlay),
         str(source), "-o", str(binary)],
        check=True, timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=30)
