"""Exercise the production transaction loop with a deterministic fake UART."""

import shlex
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

    # Compile the actual parser and every reply validator; only UART/clock are faked.
    json_alias = next(line for line in bridge.splitlines() if line.startswith("using JsonPtr ="))
    parser = "\n".join([json_alias, *(extract(signature) for signature in (
        "JsonPtr Parse(", "bool StatusValid(", "bool OpticsValid(",
        "bool PoseVersionUnsupported(", "bool PoseValid(", "bool IrValid(", "bool AuxValid(",
    ))])
    source = tmp_path / "uart_transaction.cc"
    source.write_text(r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <cJSON.h>
#include "robot_protocol.h"
using namespace desk_robot;
constexpr int ESP_OK = 0, kUart = 1, kTimeoutMs = 350;
constexpr std::size_t kMaxReply = 1920;
#define pdMS_TO_TICKS(x) (x)

int flush_result = 0, read_error = 0, writes = 0, reads = 0;
std::atomic<std::int64_t> tick{0};
std::string rx, tx;
std::size_t pos = 0;
bool interrupt_poll = false;
std::atomic<bool> poll_entered{false}, release_poll{false};

// Synchronize the fake UART read with urgent admission, not wall-clock sleeps.
// A broken gate must fail rather than hang the native test binary.
template <typename Predicate>
void wait_until(Predicate ready) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (!ready()) {
        assert(std::chrono::steady_clock::now() < deadline);
        std::this_thread::yield();
    }
}

std::int64_t esp_timer_get_time() { return tick.fetch_add(10) + 10; }
int uart_flush_input(int) { return flush_result; }
int uart_write_bytes(int, const char* s, std::size_t n) {
    ++writes;
    tx.assign(s, n);
    if (interrupt_poll && (tx == "stop\r\n" || tx == "halt\r\n")) {
        rx = "OK " + tx;
        pos = 0;
    }
    return static_cast<int>(n);
}
int uart_wait_tx_done(int, int) { return ESP_OK; }
int uart_read_bytes(int, std::uint8_t* c, int, int) {
    ++reads;
    if (read_error) return -1;
    if (interrupt_poll && tx != "stop\r\n" && tx != "halt\r\n") {
        poll_entered.store(true, std::memory_order_release);
        wait_until([] { return release_poll.load(std::memory_order_acquire); });
        tick.fetch_add(10000);
        return 0;
    }
    if (pos == rx.size()) {
        tick += 10000;
        return 0;
    }
    *c = rx[pos++];
    return 1;
}

''' + parser + r'''
struct Reply { int status; bool ok; std::string text; };
struct Bridge {
    bool enabled_ = true, uart_ready_ = true;
    std::mutex uart_mutex_;
    UrgentStopGate urgent_stop_gate_;
    Reply Transact(const std::string&, bool);
    static Reply ReadBodyReply(const Command&, const UrgentStopGate::Request&);
};
''' + extract("bool BodyWireByteValid(") + "\n" +
        extract("bool BodyWireValid(") + "\n" +
        extract("Reply Bridge::Transact(") + "\n" +
        extract("Reply Bridge::ReadBodyReply(") + r'''
void reset() {
    flush_result = read_error = writes = reads = 0;
    tick = 0;
    pos = 0;
    rx.clear();
    tx.clear();
    interrupt_poll = false;
    poll_entered = false;
    release_poll = false;
}

void check_urgent_poll_preemption(const std::string& poll, const std::string& verb) {
    reset();
    Bridge b;
    interrupt_poll = true;
    Reply reading{}, stopped{};
    std::thread reader([&] { reading = b.Transact(poll, false); });
    wait_until([] { return poll_entered.load(std::memory_order_acquire); });
    std::thread stopper([&] { stopped = b.Transact(verb, true); });
    wait_until([&] { return b.urgent_stop_gate_.preempts(false); });
    release_poll.store(true, std::memory_order_release);
    reader.join();
    stopper.join();
    assert(reading.status == 503 && !reading.ok);
    assert(reading.text == "body response superseded by urgent stop");
    assert(stopped.ok && stopped.text == "OK " + verb);
    assert(writes == 2 && tx == verb + "\r\n");
    // The first empty read may finish, but no second polling read is allowed.
    assert(reads == 1 + static_cast<int>(stopped.text.size()) + 2);
}

void check_json_telemetry() {
    // Exercise decoded cJSON keys, strict document termination and depth bounds.
    assert(Parse(R"({"text":"{[\"]}","items":[{"a":1},{"a":2}]})"));
    assert(Parse(std::string(12, '[') + "0" + std::string(12, ']')));
    assert(!Parse(std::string(13, '[') + "0" + std::string(13, ']')));
    for (const std::string wire : {
            R"({"x":})", R"({"x":1)", R"({"x":[1})", R"({"x":1} trailing)",
            R"({"x":1}{})", R"({"x":1,"x":2})", R"({"items":[{"x":1,"\u0078":2}]})",
            R"({"x":"\u0000"})"}) {
        assert(!Parse(wire));
    }
    assert(!Parse(std::string("{}") + '\0' + "{}"));

    const std::string status =
        R"({"armed":false,"watchdog_ms":500,"protocol":2,)"
        R"("motor":{"m0":0,"m1":0},)"
        R"("servo":{"lift":90,"grip":90,"lift_target":90,"grip_target":90,)"
        R"("attached":false,"position_source":"commanded"},)"
        R"("safety":{"required":true,"ready":true,"sensor":0,"fault":"none"},)"
        R"("ranges":{"present_mask":31,"valid_mask":31,"mm":[50,50,50,50,100],)"
        R"("age_ms":[0,0,0,0,0]},"touch":{"active":false,"count":0},)"
        R"("imu":{"boot_id":9,"valid":true,"family":1,"acc":[0,0,0],)"
        R"("gyro":[0,0,0],"age_ms":0},"side_ranges":{"boot_id":9}})";
    const std::string pose =
        R"({"v":1,"body_boot":9,"origin":2,"seq":1,"sample_us":1234,)"
        R"("x_mm":0,"y_mm":0,"yaw_mrad":0,"quality":"valid"})";
    const auto replace = [](std::string wire, const std::string& old,
                            const std::string& replacement) {
        const auto pos = wire.find(old);
        assert(pos != std::string::npos);
        return wire.replace(pos, old.size(), replacement);
    };
    const auto transact = [](const std::string& verb, const std::string& wire) {
        reset();
        Bridge bridge;
        rx = wire + "\r\n";
        const auto reply = bridge.Transact(verb, false);
        assert(writes == 1 && tx == verb + "\r\n");
        return reply;
    };
    for (const auto& sample : {std::make_pair("status", status),
                               std::make_pair("pose", pose)}) {
        const auto good = transact(sample.first, sample.second);
        assert(good.status == 200 && good.ok && good.text == sample.second);
        for (const auto& bad : {sample.second.substr(0, sample.second.size() - 1),
                               sample.second + "{}", std::string("{}"), std::string("[]")}) {
            const auto rejected = transact(sample.first, bad);
            assert(!rejected.ok && rejected.status != 200 && rejected.text != bad);
        }
    }
    for (const auto& bad : {
            replace(status, R"("m0":0)", R"("m0":0,"\u006d0":0)"),
            replace(status, R"("safety":{"required":true,"ready":true,"sensor":0,"fault":"none"})",
                    R"("safety":[])"),
            replace(status, R"("armed":false)",
                    R"("armed":false,"extra":)" + std::string(12, '[') + "0" +
                    std::string(12, ']')),
            replace(status, R"("ready":true,)", ""),
            replace(status, R"("watchdog_ms":500)", R"("watchdog_ms":"500")")}) {
        const auto rejected = transact("status", bad);
        assert(!rejected.ok && rejected.status == 504 && rejected.text != bad);
    }
    for (const auto& bad : {
            replace(pose, R"("v":1)", R"("v":1,"\u0076":1)"),
            replace(pose, R"("sample_us":1234,)", ""),
            replace(pose, R"("origin":2)", R"("origin":0)"),
            replace(pose, R"("seq":1)", R"("seq":1.5)")}) {
        const auto rejected = transact("pose", bad);
        assert(!rejected.ok && rejected.status == 503 && rejected.text != bad);
    }
    const auto version = transact("pose", replace(pose, R"("v":1)", R"("v":2)"));
    assert(!version.ok && version.status == 501);
}

int main() {
    check_json_telemetry();
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
    rx = "OK stop\r\nERR ping refused\r\nOK ping\r\n";
    a = b.Transact("ping", true);
    assert(a.status == 400 && !a.ok && a.text == "ERR ping refused");
    reset();
    rx = "ERR input unknown_command\r\n";
    a = b.Transact("pose", false);
    assert(a.status == 501 && !a.ok && a.text == "pose unsupported by body firmware");
    reset();
    rx = "{}\r\n";
    a = b.Transact("pose", false);
    assert(a.status == 503 && !a.ok && a.text == "malformed or unsupported pose response");
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
    for (const std::string poll : {"status", "aux", "optics", "ir", "pose"}) {
        for (const std::string verb : {"stop", "halt"}) {
            check_urgent_poll_preemption(poll, verb);
        }
    }
}
''')
    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++17 compiler required"
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "libcjson"], text=True,
    ))
    binary = tmp_path / "uart_transaction"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
         "-fsanitize=address,undefined", "-fno-sanitize-recover=all", *pie_flags,
         "-I", str(overlay),
         str(source), *flags, "-o", str(binary)],
        check=True, timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
