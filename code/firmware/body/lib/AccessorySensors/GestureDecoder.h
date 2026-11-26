#pragma once
#include <cstdint>
namespace desk_robot {

// Nonblocking bounded APDS9960 gesture FIFO decoder. Raw gesture ratio logic
// adapted from SparkFun's APDS9960 library (MIT license), but without its
// blocking delay + while(true) readGesture() loop.
// Gesture direction is a candidate until physical wave/false-positive tests.
class GestureDecoder {
 public:
  enum class PollAction : std::uint8_t { None, Read, Clear };

  // A missed or overflowing FIFO invalidates the entire gesture, not just
  // the current batch. Wait for a clean idle status before accepting a new
  // session; the caller can clear the hardware FIFO with one bounded write.
  void invalidate() {
    reset();
    collecting_ = false;
    discarding_ = true;
  }
  void restart() {
    reset();
    collecting_ = discarding_ = false;
  }
  PollAction poll_status(std::uint8_t state, std::uint32_t now_ms,
                         std::uint8_t& direction) {
    direction = 0;
    if ((state & 0x02U) ||
        (collecting_ && now_ms - started_ms_ > 700U)) invalidate();
    if (discarding_) {
      if (state & 0x03U) return PollAction::Clear;
      discarding_ = false;
      return PollAction::None;
    }
    if ((state & 0x01U) == 0U) {
      if (collecting_) direction = finish();
      collecting_ = false;
      return PollAction::None;
    }
    return PollAction::Read;
  }
  void begin_batch(std::uint32_t now_ms) {
    if (!collecting_) {
      reset();
      started_ms_ = now_ms;
      collecting_ = true;
    }
  }

  // Direction code: 0 none, 1 up, 2 down, 3 left, 4 right.
  void push(std::uint8_t up, std::uint8_t down,
            std::uint8_t left, std::uint8_t right) {
    // A clipped quadrant has lost directional information. Do not splice
    // valid samples across a saturated record in the same FIFO session.
    if (clipped_) return;
    if (up == 255 || down == 255 || left == 255 || right == 255) {
      clipped_ = true;
      return;
    }
    const unsigned ud = up + down;
    const unsigned lr = left + right;
    if (ud < 40 || lr < 40) return;
    const int uratio = (100 * (int(up) - int(down))) / int(ud);
    const int lratio = (100 * (int(left) - int(right))) / int(lr);
    if (samples_ == 0) {
      initial_ud_ = uratio;
      initial_lr_ = lratio;
      initial_ = {up, down, left, right};
    }
    final_ud_ = uratio;
    final_lr_ = lratio;
    final_ = {up, down, left, right};
    if (samples_ < 255) ++samples_;
  }

  std::uint8_t finish() {
    std::uint8_t direction = 0;
    if (!clipped_ && samples_ >= 3) {
      const int ud = final_ud_ - initial_ud_;
      const int lr = final_lr_ - initial_lr_;
      const int abs_ud = ud < 0 ? -ud : ud;
      const int abs_lr = lr < 0 ? -lr : lr;
      // Reject diagonals and weak noise. SparkFun's sign conventions:
      // falling U/D ratio means UP and falling L/R ratio means LEFT.
      // A ratio alone can move when just one diode changes or both see
      // uneven common-mode glare. Require opposing endpoint motion on
      // the winning pair; the orthogonal pair may legitimately be steady.
      if (abs_ud >= 30 && abs_ud > abs_lr * 2 &&
          opposed(initial_.up, final_.up, initial_.down, final_.down, ud))
        direction = ud < 0 ? 1 : 2;
      else if (abs_lr >= 30 && abs_lr > abs_ud * 2 &&
               opposed(initial_.left, final_.left, initial_.right, final_.right, lr))
        direction = lr < 0 ? 3 : 4;
    }
    reset();
    return direction;
  }
  void reset() {
    samples_ = 0;
    clipped_ = false;
    initial_ = final_ = {};
    initial_ud_ = initial_lr_ = final_ud_ = final_lr_ = 0;
  }

 private:
  struct Quadrants { std::uint8_t up, down, left, right; };
  static bool opposed(std::uint8_t first_a, std::uint8_t last_a,
                      std::uint8_t first_b, std::uint8_t last_b, int delta) {
    return delta < 0 ? last_a < first_a && last_b > first_b
                     : last_a > first_a && last_b < first_b;
  }
  Quadrants initial_{}, final_{};
  bool clipped_ = false;
  bool collecting_ = false, discarding_ = false;
  std::uint32_t started_ms_ = 0;
  std::uint8_t samples_ = 0;
  int initial_ud_ = 0, initial_lr_ = 0;
  int final_ud_ = 0, final_lr_ = 0;
};
} // namespace desk_robot
