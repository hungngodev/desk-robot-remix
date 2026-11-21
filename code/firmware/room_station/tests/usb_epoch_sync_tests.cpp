#include "usb_epoch_sync.h"

#include <assert.h>
#include <stdint.h>
#include <string>

using desk_robot_room::UsbEpochSync;

static bool feed(UsbEpochSync& parser, const std::string& input) {
  bool replied = false;
  for (const char byte : input) {
    if (parser.consume(static_cast<uint8_t>(byte))) replied = true;
  }
  return replied;
}

int main() {
  UsbEpochSync parser;
  assert(!feed(parser, "SYNC 0123456789abcde"));
  assert(feed(parser, "f\n"));
  assert(std::string(parser.token()) == "0123456789abcdef");
  assert(!feed(parser, "SYNC 0123456789abcdeF\n"));
  assert(!feed(parser, "SYNC 0123456789abcdef extra\n"));
  assert(!feed(parser, "SYNC 0123456789abcdef\r\n"));
  assert(!feed(parser, "ignored old JSON telemetry\n"));
  assert(!feed(parser, "SYNC " + std::string(100, '0') + "\n"));
  assert(feed(parser, "SYNC fedcba9876543210\n"));
  assert(std::string(parser.token()) == "fedcba9876543210");
  // Fragments cannot acknowledge an epoch until the entire line arrives.
  assert(!feed(parser, "SYNC deadbeef"));
  assert(!feed(parser, "1234567"));
  assert(feed(parser, "8\n"));
  assert(std::string(parser.token()) == "deadbeef12345678");
}
