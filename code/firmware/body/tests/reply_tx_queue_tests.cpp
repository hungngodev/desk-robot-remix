#include "ReplyTxQueue.h"
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <string>

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

int main() {
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
  assert(framed.pending() == 0 && framed.dropped() == 6);
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
