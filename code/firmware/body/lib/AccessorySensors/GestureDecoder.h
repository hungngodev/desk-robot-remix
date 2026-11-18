#pragma once
#include <cstdint>
namespace desk_robot {

// Nonblocking bounded APDS9960 gesture FIFO decoder. Raw gesture ratio logic
// adapted from SparkFun's APDS9960 library (MIT license), but without its
// blocking delay + while(true) readGesture() loop.
// Gesture direction is a candidate until physical wave/false-positive tests.
class GestureDecoder {
 public:
  // Direction code: 0 none, 1 up, 2 down, 3 left, 4 right.
  void push(std::uint8_t up, std::uint8_t down,
            std::uint8_t left, std::uint8_t right) {
    const unsigned ud = up + down;
    const unsigned lr = left + right;
    if (ud < 40 || lr < 40) return;
    const int uratio = (100 * (int(up) - int(down))) / int(ud);
    const int lratio = (100 * (int(left) - int(right))) / int(lr);
    if (samples_ == 0) {
      initial_ud_ = uratio;
      initial_lr_ = lratio;
    }
    final_ud_ = uratio;
    final_lr_ = lratio;
    if (samples_ < 255) ++samples_;
  }

  std::uint8_t finish() {
    std::uint8_t direction = 0;
    if (samples_ >= 3) {
      const int ud = final_ud_ - initial_ud_;
      const int lr = final_lr_ - initial_lr_;
      const int abs_ud = ud < 0 ? -ud : ud;
      const int abs_lr = lr < 0 ? -lr : lr;
      // Reject diagonals and weak noise. SparkFun's sign conventions:
      // falling U/D ratio means UP and falling L/R ratio means LEFT.
      if (abs_ud >= 30 && abs_ud > abs_lr * 2)
        direction = ud < 0 ? 1 : 2;
      else if (abs_lr >= 30 && abs_lr > abs_ud * 2)
        direction = lr < 0 ? 3 : 4;
    }
    reset();
    return direction;
  }
  void reset() {
    samples_ = 0;
    initial_ud_ = initial_lr_ = final_ud_ = final_lr_ = 0;
  }

 private:
  std::uint8_t samples_ = 0;
  int initial_ud_ = 0, initial_lr_ = 0;
  int final_ud_ = 0, final_lr_ = 0;
};
} // namespace desk_robot
