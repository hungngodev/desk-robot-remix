"""Exercise the production transaction loop with a deterministic fake UART."""

import shutil
import subprocess
import sys
from pathlib import Path


def test_uart_receive_failure_and_frame_boundaries(tmp_path):
    overlay = Path(__file__).resolve().parents[1] / "overlay"
    bridge = (overlay / "robot_bridge.cc").read_text()

    def extract(signature):
        start = bridge.index(signature)
        return bridge[start:bridge.index("\n}", start) + 2]

    source = tmp_path / "uart_transaction.cc"
    source.write_text(r'''
#include <cassert>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include "robot_protocol.h"
using namespace desk_robot;
constexpr int ESP_OK = 0, kUart = 1, kTimeoutMs = 350;
constexpr std::size_t kMaxReply = 1920;
#define pdMS_TO_TICKS(x) (x)

int flush_result = 0, read_error = 0, writes = 0, reads = 0;
std::int64_t tick = 0;
std::string rx, tx;
std::size_t pos = 0;
std::int64_t esp_timer_get_time() { return tick += 10; }
int uart_flush_input(int) { return flush_result; }
int uart_write_bytes(int, const char* s, std::size_t n) {
    ++writes;
    tx.assign(s, n);
    return static_cast<int>(n);
}
int uart_wait_tx_done(int, int) { return ESP_OK; }
int uart_read_bytes(int, std::uint8_t* c, int, int) {
    ++reads;
    if (read_error) return -1;
    if (pos == rx.size()) {
        tick += 10000;
        return 0;
    }
    *c = rx[pos++];
    return 1;
}

// These cases exercise ACK framing, not JSON semantics.
std::unique_ptr<int> Parse(const std::string&) { return {}; }
bool PoseVersionUnsupported(int*) { return false; }
bool StatusValid(int*) { return false; }
bool AuxValid(int*) { return false; }
bool IrValid(int*) { return false; }
bool PoseValid(int*) { return false; }
bool OpticsValid(int*) { return false; }
struct Reply { int status; bool ok; std::string text; };
struct Bridge {
    bool enabled_ = true, uart_ready_ = true;
    std::mutex uart_mutex_;
    UrgentStopGate urgent_stop_gate_;
    Reply Transact(const std::string&, bool);
};
''' + extract("bool BodyWireByteValid(") + "\n" +
        extract("bool BodyWireValid(") + "\n" +
        extract("Reply Bridge::Transact(") + r'''
void reset() {
    flush_result = read_error = writes = reads = 0;
    tick = 0;
    pos = 0;
    rx.clear();
    tx.clear();
}
int main() {
    Bridge b;
    reset();
    flush_result = -1;
    rx = "OK ping\r\n";
    auto a = b.Transact("ping", true);
    assert(a.status == 503 && !a.ok && writes == 0 && reads == 0);
    for (const std::string verb : {"stop", "halt"}) {
        reset();
        flush_result = -1;
        rx = "OK " + verb + "\r\n";
        a = b.Transact(verb, true);
        assert(a.status == 503 && !a.ok && writes == 1 && reads == 0);
        assert(tx == verb + "\r\n");
    }
    reset();
    read_error = 1;
    a = b.Transact("ping", true);
    assert(a.status == 503 && !a.ok && writes == 1 && reads == 1);
    reset();
    rx = "EVT startup\r\nOK ping\r\n";
    a = b.Transact("ping", true);
    assert(a.ok && writes == 1);
    reset();
    rx = std::string(1920, 'x') + "\nOK ping\n";
    assert(b.Transact("ping", true).ok);
    reset();
    rx = std::string(1921, 'x') + "\nOK ping\n";
    a = b.Transact("ping", true);
    assert(a.status == 503 && !a.ok && reads == 1921);
    reset();
    rx = std::string("OK pi\0ng\n", 9);
    a = b.Transact("ping", true);
    assert(a.status == 503 && !a.ok);
    reset();
    rx = "OK pi\rng\n";
    a = b.Transact("ping", true);
    assert(a.status == 503 && !a.ok);
    reset();
    rx = "OK ping";
    a = b.Transact("ping", true);
    assert(a.status == 504 && !a.ok);
}
''')
    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++17 compiler required"
    binary = tmp_path / "uart_transaction"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", *pie_flags, "-I", str(overlay),
         str(source), "-o", str(binary)],
        check=True, timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
