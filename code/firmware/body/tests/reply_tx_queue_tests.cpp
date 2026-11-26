#include "ReplyTxQueue.h"
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <string>
#include <utility>

struct FakeSerial {
  int free = 0;
  std::size_t per_write = 1024;
  std::string sent;
  int availableForWrite() const { return free; }
  std::size_t write(const std::uint8_t* data, std::size_t count) {
    const auto accepted = std::min({count, static_cast<std::size_t>(free), per_write});
    sent.append(reinterpret_cast<const char*>(data), accepted);
    free -= static_cast<int>(accepted);
    return accepted;
  }
};

using Queue = desk_robot::ReplyTxQueue<128>;
static_assert(noexcept(std::declval<Queue&>().enqueue_line(nullptr)), "normal enqueue must not throw");
static_assert(noexcept(std::declval<Queue&>().enqueue_priority_line(nullptr)), "urgent enqueue must not throw");
static_assert(noexcept(std::declval<const Queue&>().pending()), "pending query must not throw");
static_assert(noexcept(std::declval<const Queue&>().dropped()), "drop count query must not throw");
// The generic serial backend can allocate or throw; do not promise otherwise.
static_assert(!noexcept(std::declval<Queue&>().drain(std::declval<FakeSerial&>())), "serial drain can propagate backend exceptions");

void test_distinct_urgent_receipt_survives_duplicate_burst() {
  for (const bool stop_first : {false, true}) {
    const char* first = stop_first ? "OK stop" : "OK halt";
    const char* other = stop_first ? "OK halt" : "OK stop";
    for (const std::size_t prefix : {0U, 1U, 8U}) {
      desk_robot::ReplyTxQueue<16> queue;
      FakeSerial serial;
      assert(queue.enqueue_line("01234567890123"));
      assert(queue.enqueue_priority_line(first));
      assert(queue.enqueue_priority_line(first));
      serial.free = 16;
      assert(queue.drain(serial, prefix) == prefix);
      assert(queue.enqueue_priority_line(other));
      assert(queue.dropped() == 1);
      assert(queue.pending() == 34 - prefix);
      assert(!queue.enqueue_priority_line(first));
      assert(queue.dropped() == 2);
      while (queue.pending()) {
        serial.free = 16;
        serial.per_write = 3;
        assert(queue.drain(serial) > 0);
      }
      assert(serial.sent == std::string(first) + "\r\n" + other +
                               "\r\n01234567890123\r\n");
    }
  }
}

// Move the next round's normal ring start exactly one byte forward modulo 17.
void advance_ring(desk_robot::ReplyTxQueue<17>& queue, FakeSerial& serial,
                  std::string& expected, std::size_t refill_bytes) {
  const auto send = [&](std::size_t length) {
    const std::string frame(length - 2, 'a');
    assert(queue.enqueue_line(frame.c_str()));
    expected += frame + "\r\n";
    while (queue.pending()) {
      serial.free = 32;
      assert(queue.drain(serial) == 1);
    }
  };
  if (refill_bytes == 0) {
    send(3);
    send(15);
  } else {
    send(18 - refill_bytes);
  }
  assert(serial.sent == expected);
}

// Cover every physical ring start and every split of the first status frame.
// Refill freed normal bytes before the urgent burst and keep flooding while
// the UART alternates between blocked and single-byte writes.
void test_urgent_under_sustained_ring_pressure() {
  for (std::size_t split = 0; split <= 8; ++split) {
    desk_robot::ReplyTxQueue<17> queue;
    FakeSerial serial;
    std::string expected;
    std::size_t drops = 0;
    for (std::size_t round = 0; round < 17; ++round) {
      assert(queue.enqueue_line("abcdef"));
      assert(queue.enqueue_line("1234567"));
      assert(queue.pending() == 17);
      serial.per_write = 1;
      for (std::size_t i = 0; i < split; ++i) {
        serial.free = 1;
        assert(queue.drain(serial) == 1);
      }
      const std::string refill(split >= 3 ? split - 2 : 0, 'r');
      if (!refill.empty()) assert(queue.enqueue_line(refill.c_str()));
      const char* first = round % 2 ? "OK halt" : "OK stop";
      const char* other = round % 2 ? "OK stop" : "OK halt";
      assert(queue.enqueue_priority_line(first));
      assert(queue.enqueue_priority_line(first));
      assert(queue.enqueue_priority_line(other));  // replace only duplicate tail
      ++drops;
      const std::size_t before = queue.pending();
      for (const int free : {0, -1, 0}) {
        serial.free = free;
        assert(queue.drain(serial) == 0);
        assert(queue.pending() == before);
      }
      // At most the already-started status and first urgent receipt precede
      // the second urgent slot. Flood attempts cannot extend this bound.
      const std::size_t first_end = (split > 0 && split < 8 ? 8 - split : 0) + 9;
      serial.per_write = 7;
      for (std::size_t i = 0; i < first_end;) {
        assert(!queue.enqueue_line("012345678901234"));
        ++drops;
        serial.free = 32;
        const auto written = queue.drain(serial, first_end - i);
        assert(written > 0 && written <= 7);
        i += written;
        assert(queue.pending() == before - i);
      }
      serial.per_write = 1;
      assert(queue.enqueue_priority_line(first));  // reuse the freed urgent slot
      assert(!queue.enqueue_priority_line(other));
      ++drops;
      const std::string urgent = std::string(first) + "\r\n" + other + "\r\n" + first + "\r\n";
      expected += split == 0 ? urgent + "abcdef\r\n" : "abcdef\r\n" + urgent;
      expected += "1234567\r\n";
      if (!refill.empty()) expected += refill + "\r\n";
      for (std::size_t i = 0; queue.pending() && i < 44; ++i) {
        serial.free = 32;
        assert(queue.drain(serial) == 1);
      }
      assert(queue.pending() == 0 && queue.dropped() == drops);
      assert(serial.sent == expected);
      advance_ring(queue, serial, expected, refill.empty() ? 0 : split);
    }
  }
}

int main() {
  test_urgent_under_sustained_ring_pressure();
  test_distinct_urgent_receipt_survives_duplicate_burst();
  desk_robot::ReplyTxQueue<128> head, usb;
  const std::string status(94, 's');
  assert(head.enqueue_line(status.c_str()));
  FakeSerial head_serial, usb_serial;
  head_serial.free = 0;
  assert(head.drain(head_serial) == 0); // full hardware FIFO: no waiting
  assert(head.pending() == status.size() + 2);
  head_serial.free = 100;
  assert(head.drain(head_serial, 100) == 32); // hard per-cycle cap
  assert(head_serial.sent == status.substr(0, 32));
  assert(usb.enqueue_line("OK stop"));
  usb_serial.free = 16;
  assert(usb.drain(usb_serial) == 9);
  assert(usb_serial.sent == "OK stop\r\n");
  assert(head_serial.sent.size() == 32); // ports have separate queues
  while (head.pending() != 0) {
    head_serial.free = 128;
    assert(head.drain(head_serial) <= 32);
  }
  assert(head_serial.sent == status + "\r\n");

  desk_robot::ReplyTxQueue<24> congested;
  assert(congested.enqueue_line("1234567890123456"));
  assert(!congested.enqueue_line("second")); // no partial frame
  assert(congested.pending() == 18 && congested.dropped() == 1);
  FakeSerial sink;
  sink.free = 7;
  sink.per_write = 4;
  assert(congested.drain(sink) == 4); // short write retained
  assert(congested.enqueue_line("two")); // circular queue wrap
  while (congested.pending()) {
    sink.free = 24;
    assert(congested.drain(sink) > 0);
  }
  assert(sink.sent == "1234567890123456\r\ntwo\r\n");
  assert(!congested.enqueue_line(std::string(25, 'x').c_str()));
  assert(congested.dropped() == 2);
  // Already-full normal queue must not swallow a completed STOP/HALT receipt.
  desk_robot::ReplyTxQueue<128> backlog;
  const std::string one(60, 'a'), two(60, 'b');
  assert(backlog.enqueue_line(one.c_str()));
  assert(backlog.enqueue_line(two.c_str()));
  assert(!backlog.enqueue_line("another ordinary status"));
  assert(backlog.enqueue_priority_line("OK halt"));
  assert(backlog.enqueue_priority_line("OK stop"));
  assert(!backlog.enqueue_priority_line("OK halt")); // bounded urgent lane
  assert(backlog.dropped() == 2);
  FakeSerial backlog_serial;
  backlog_serial.free = 0;
  assert(backlog.drain(backlog_serial) == 0);
  while (backlog.pending()) {
    backlog_serial.free = 128;
    const auto written = backlog.drain(backlog_serial);
    assert(written > 0 && written <= 32);
  }
  assert(backlog_serial.sent == "OK halt\r\nOK stop\r\n" +
         one + "\r\n" + two + "\r\n");

  // Put CR at the last ring byte and LF at the first. Fill every normal
  // byte, then reject a new frame without modifying the queued tail.
  desk_robot::ReplyTxQueue<16> exact;
  FakeSerial exact_serial;
  assert(exact.enqueue_line("abc"));
  exact_serial.free = 16;
  assert(exact.drain(exact_serial) == 5);
  assert(exact.enqueue_line("0123456789"));
  assert(exact.enqueue_line("zz"));
  assert(exact.pending() == 16);
  assert(!exact.enqueue_line("x"));
  assert(exact.pending() == 16 && exact.dropped() == 1);
  assert(exact.enqueue_priority_line("OK stop"));
  assert(exact.pending() == 25);
  exact_serial.free = 0;
  assert(exact.drain(exact_serial) == 0);
  assert(exact.pending() == 25);
  exact_serial.free = 16;
  assert(exact.drain(exact_serial) == 9);
  assert(exact_serial.sent == "abc\r\nOK stop\r\n");
  assert(exact.pending() == 16);
  // Start the wrapped status and stop just after CR, not after LF.
  exact_serial.free = 16;
  assert(exact.drain(exact_serial, 11) == 11);
  assert(exact_serial.sent == "abc\r\nOK stop\r\n0123456789\r");
  assert(exact.enqueue_priority_line("OK halt"));
  assert(exact.enqueue_priority_line("OK stop"));
  assert(!exact.enqueue_priority_line("OK halt"));
  assert(exact.pending() == 23 && exact.dropped() == 2);
  exact_serial.free = 16;
  assert(exact.drain(exact_serial) == 1); // finish LF before either receipt
  assert(exact.pending() == 22);
  exact_serial.per_write = 0;
  assert(exact.drain(exact_serial) == 0);
  assert(exact.pending() == 22);
  exact_serial.per_write = 2;
  assert(exact.drain(exact_serial) == 2);
  assert(exact.pending() == 20);
  assert(!exact.enqueue_priority_line("OK halt")); // partial slot is occupied
  exact_serial.per_write = 16;
  exact_serial.free = 16;
  assert(exact.drain(exact_serial) == 7);
  assert(exact.pending() == 13);
  assert(exact.enqueue_priority_line("OK halt")); // reuse freed urgent slot
  assert(exact.pending() == 22 && exact.dropped() == 3);
  while (exact.pending()) {
    exact_serial.free = 16;
    assert(exact.drain(exact_serial) > 0);
  }
  assert(exact_serial.sent == "abc\r\nOK stop\r\n0123456789\r\n"
                              "OK halt\r\nOK stop\r\nOK halt\r\nzz\r\n");

  // Once a JSON line starts, complete it before the priority lane. Never
  // splice "OK halt" into an already transmitted status frame.
  desk_robot::ReplyTxQueue<128> partial;
  assert(partial.enqueue_line(one.c_str()));
  assert(partial.enqueue_line(two.c_str()));
  FakeSerial partial_serial;
  partial_serial.free = 3;
  partial_serial.per_write = 2;
  assert(partial.drain(partial_serial) == 2);
  assert(partial.enqueue_priority_line("OK halt"));
  while (partial.pending()) {
    partial_serial.free = 128;
    // A nondivisor of the remaining first frame forces the drain to
    // stop at its delimiter even when the next status fits in this write.
    partial_serial.per_write = 7;
    const auto written = partial.drain(partial_serial);
    assert(written > 0 && written <= 7);
  }
  assert(partial_serial.sent == one + "\r\nOK halt\r\n" + two + "\r\n");

  assert(!partial.enqueue_priority_line(std::string(63, 'x').c_str()));
  assert(partial.dropped() == 1);
  // Malformed reply content must never create a second apparent UART
  // command response. Reject before changing either queue's state.
  desk_robot::ReplyTxQueue<64> framed;
  assert(!framed.enqueue_line("status\r\nOK arm"));
  assert(!framed.enqueue_line("status\nOK arm"));
  assert(!framed.enqueue_priority_line("OK halt\r\nOK arm"));
  assert(!framed.enqueue_priority_line("OK stop\nOK arm"));
  assert(!framed.enqueue_line(std::string(100000, 'x').c_str()));
  assert(!framed.enqueue_priority_line(std::string(100000, 'x').c_str()));
  assert(!framed.enqueue_line(""));
  assert(!framed.enqueue_priority_line(""));
  assert(framed.pending() == 0 && framed.dropped() == 8);
  assert(framed.enqueue_line("status"));
  assert(framed.enqueue_priority_line("OK stop"));
  FakeSerial framed_serial;
  while (framed.pending()) {
    framed_serial.free = 128;
    assert(framed.drain(framed_serial) > 0);
  }
  assert(framed_serial.sent == "OK stop\r\nstatus\r\n");

  std::cout << "PASS bounded independent WROOM UART reply queues with urgent stop receipts\n";
}
