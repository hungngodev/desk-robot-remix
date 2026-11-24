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
  // A port can close after an incomplete write, without resetting the
  // independently powered Feather. The next bare challenge is swallowed.
  assert(!feed(parser, "SYNC dead"));
  assert(!feed(parser, "SYNC 0123456789abcdef\n"));
  const std::string next = "SYNC fedcba9876543210\n";
  const std::string old = "SYNC 0123456789abcdef\n";
  // Verify every interrupted write boundary, including a complete stale
  // nonce lacking its final newline. Only the new nonce is authoritative.
  for (size_t n = 0; n < old.size(); ++n) {
    UsbEpochSync reconnect;
    assert(!feed(reconnect, old.substr(0, n)));
    assert(feed(reconnect, "\n" + next));
    assert(std::string(reconnect.token()) == "fedcba9876543210");
  }
  UsbEpochSync overflow;
  assert(!feed(overflow, std::string(100, 'x')));
  assert(feed(overflow, "\n" + next));
  assert(std::string(overflow.token()) == "fedcba9876543210");
}
