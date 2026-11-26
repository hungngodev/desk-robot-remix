"""Shared byte fixtures for the Sense C++ and Mac Python wire boundaries."""

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from desk_robot.spatial_pose import PoseError, decode_pose
from desk_robot.transport import HeadError, _MjpegFrames, _response_object

POSE = (
    b'{"v":1,"body_boot":16909060,"origin":270544960,"seq":4294967294,'
    b'"sample_us":9007199254740991,"x_mm":-1000000,"y_mm":65537,'
    b'"yaw_mrad":-3142,"quality":"valid","robot_id":"robot-01",'
    b'"head_boot":2712847316}'
)
JPEG = bytes.fromhex("ff d8 00 01 02 03 ff 00 04 05 ff d9")


@pytest.fixture(scope="module")
def cpp_gate(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ host compiler unavailable")
    overlay = Path(__file__).resolve().parents[1] / "firmware/head/overlay"
    build = tmp_path_factory.mktemp("pose-wire")
    source = build / "gate.cc"
    executable = build / "gate"
    bridge = (overlay / "robot_bridge.cc").read_text()
    stream = bridge.split("void Bridge::CameraStreamTask(", 1)[1]
    # Compile the actual production formatter, not a second implementation.
    camera_format = stream.split("const int n = snprintf(", 1)[1].split(";", 1)[0]
    pose_format = bridge.split("const auto decimal = ", 1)[1].split(";", 1)[0]
    source.write_text(r'''
#include <cstdio>
#include <iostream>
#include <iterator>
#include <string>
#include <string_view>
#include "robot_protocol.h"

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string wire{std::istreambuf_iterator<char>(std::cin), {}};
    if (std::string_view(argv[1]) == "camera") {
        const auto* jpeg = &wire;
        struct { std::uint32_t boot_nonce_; } value{0xa1b2c3d4U};
        const auto* bridge = &value;
        constexpr auto seq = 0xfffffffeU;
        constexpr auto completed = 9223372036854775807LL;
        char headers[320] = {};
        #define CONFIG_DESK_ROBOT_ID "robot-01"
        const int n = snprintf(''' + camera_format + r''';
        if (n < 0 || static_cast<std::size_t>(n) >= sizeof(headers)) return 2;
        std::cout << "--deskrobotframe\r\n";
        std::cout.write(headers, n);
        std::cout.write(wire.data(), static_cast<std::streamsize>(wire.size()));
        std::cout << "\r\n";
        return 0;
    }
    if (std::string_view(argv[1]) == "sample") {
        struct { double valuedouble; } value{9007199254740991.0};
        const auto* sample = &value;
        const auto decimal = ''' + pose_format + r''';
        std::cout << decimal;
        return 0;
    }
    if (std::string_view(argv[1]) == "json")
        return desk_robot::JsonWireBounded(wire) ? 0 : 1;
    if (std::string_view(argv[1]) == "jpeg")
        return desk_robot::CompleteJpeg(
            reinterpret_cast<const std::uint8_t*>(wire.data()), wire.size()) ? 0 : 1;
    return 2;
}
''')
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-I", str(overlay),
         str(source), "-o", str(executable)],
        check=True, capture_output=True, timeout=30,
    )

    def accepts(kind, wire=b"", *, emit=False):
        result = subprocess.run(
            [str(executable), kind], input=wire, capture_output=True, timeout=5,
        )
        if emit:
            assert result.returncode == 0, result.stderr
            return result.stdout
        assert result.returncode in (0, 1), result.stderr
        return result.returncode == 0

    return accepts


def test_pose_wire_exact_signed_and_unsigned_values(cpp_gate):
    assert cpp_gate("json", POSE)
    receipt = decode_pose(_response_object(httpx.Response(200, content=POSE)), "robot-01", 1.0)
    assert (receipt.body_boot, receipt.origin, receipt.seq, receipt.head_boot) == (
        0x01020304, 0x10203040, 0xFFFFFFFE, 0xA1B2C3D4,
    )
    assert receipt.sample_us == (1 << 53) - 1
    assert cpp_gate("sample", emit=True) == str(receipt.sample_us).encode("ascii")
    assert (receipt.x_mm, receipt.y_mm, receipt.yaw_mrad) == (-1000000, 65537, -3142)
    assert receipt.quality == "valid"


@pytest.mark.parametrize("wire", [
    POSE.replace(b'"valid"', br'"valid\u0000"'),
    POSE.replace(b'"robot-01"', br'"robot-01\u0000other"'),
    POSE.replace(b'"sample_us"', br'"sample_us\u0000"'),
    POSE.replace(b'"valid"', b'"valid\x00"'),
    POSE + b"\x00",
])
def test_pose_wire_nul_is_not_a_valid_receipt(cpp_gate, wire):
    assert not cpp_gate("json", wire)
    with pytest.raises((HeadError, PoseError)):
        decode_pose(_response_object(httpx.Response(200, content=wire)), "robot-01", 1.0)


# Match CameraStreamTask's decimal HTTP headers; the payload is deliberately
# a framing fixture, not a decodable photographic image.
PART = (
    b"--deskrobotframe\r\n"
    b"Content-Type: image/jpeg\r\n"
    b"Content-Length: 12\r\n"
    b"X-Desk-Camera-Robot-Id: robot-01\r\n"
    b"X-Desk-Camera-Boot: 2712847316\r\n"
    b"X-Desk-Camera-Sequence: 4294967294\r\n"
    b"X-Desk-Camera-Complete-Us: 9223372036854775807\r\n\r\n"
    + JPEG + b"\r\n"
)


def test_camera_wire_binary_nul_and_identity_survive_fragmentation(cpp_gate):
    assert cpp_gate("jpeg", JPEG)
    assert not cpp_gate("jpeg", JPEG + b"\x00")
    emitted = cpp_gate("camera", JPEG, emit=True)
    assert emitted == PART
    parser = _MjpegFrames("robot-01")
    received = []
    for byte in emitted:
        received.extend(parser.feed(bytes([byte])))
    assert received == [(JPEG, (0xA1B2C3D4, 0xFFFFFFFE, (1 << 63) - 1))]


@pytest.mark.parametrize("field", [
    b"robot-01", b"2712847316", b"4294967294", b"9223372036854775807",
])
def test_camera_wire_nul_cannot_modify_identity(field):
    wire = PART.replace(field, field + b"\x00", 1)
    with pytest.raises(ValueError):
        _MjpegFrames("robot-01").feed(wire)
