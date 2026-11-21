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
  std::cout << "PASS bounded independent WROOM UART reply queues\n";
}
