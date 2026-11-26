#include "usb_epoch_sync.h"

#include <assert.h>
#include <stdint.h>
#include <string>
#include <vector>

using desk_robot_room::UsbEpochSync;

static std::vector<std::string> replies(UsbEpochSync& parser,
                                        const std::string& input) {
  std::vector<std::string> tokens;
  for (const char byte : input) {
    if (parser.consume(static_cast<uint8_t>(byte))) {
      assert(byte == '\n');
      tokens.emplace_back(parser.token());
    }
  }
  return tokens;
}

static bool feed(UsbEpochSync& parser, const std::string& input) {
  return !replies(parser, input).empty();
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
    const auto tokens = replies(reconnect, "\n" + next);
    // A complete old request without its delimiter can legitimately be
    // acknowledged first. The host must match its own new nonce.
    if (n == old.size() - 1) {
      assert((tokens == std::vector<std::string>{"0123456789abcdef", "fedcba9876543210"}));
    } else {
      assert((tokens == std::vector<std::string>{"fedcba9876543210"}));
    }
    assert(std::string(reconnect.token()) == "fedcba9876543210");
  }
  // Check the full byte domain at every position. A malformed request
  // must neither acknowledge nor overwrite a previously accepted token.
  const std::string seed = "deadbeef12345678";
  const std::string valid = "SYNC 0123456789abcdef";
  for (size_t pos = 0; pos < valid.size(); ++pos) {
    for (unsigned value = 0; value <= 255; ++value) {
      const bool hex = (value >= '0' && value <= '9') ||
          (value >= 'a' && value <= 'f');
      const bool accepted = pos < 5 ? value == static_cast<unsigned>(valid[pos]) : hex;
      std::string candidate = valid;
      candidate[pos] = static_cast<char>(value);
      UsbEpochSync check;
      assert(feed(check, "SYNC " + seed + "\n"));
      const auto tokens = replies(check, candidate + "\n");
      if (accepted) {
        assert((tokens == std::vector<std::string>{candidate.substr(5)}));
        assert(std::string(check.token()) == candidate.substr(5));
      } else {
        assert(tokens.empty());
        assert(std::string(check.token()) == seed);
      }
      assert((replies(check, next) == std::vector<std::string>{"fedcba9876543210"}));
    }
  }
  // Reused request storage must not pad a short new line with old bytes.
  for (size_t n = 0; n < valid.size(); ++n) {
    UsbEpochSync check;
    assert(feed(check, "SYNC " + seed + "\n"));
    assert(!feed(check, valid.substr(0, n) + "\n"));
    assert(std::string(check.token()) == seed);
  }
  assert((replies(parser, old + next + old) ==
          std::vector<std::string>{"0123456789abcdef", "fedcba9876543210", "0123456789abcdef"}));
  UsbEpochSync overflow;
  assert(!feed(overflow, std::string(100, 'x')));
  assert(feed(overflow, "\n" + next));
  assert(std::string(overflow.token()) == "fedcba9876543210");
}
