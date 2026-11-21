#include "RangeScanOrder.h"

#include <iostream>
#include <stdexcept>

#define CHECK(expr) do { if (!(expr)) throw std::runtime_error(#expr); } while (false)

int main() {
  try {
    desk_robot::RangeScanOrder five(false);
    for (int i = 0; i < 100; ++i)
      CHECK(five.next() == i % 5);
    desk_robot::RangeScanOrder eight(true);
    for (int cycle = 0; cycle < 100; ++cycle) {
      for (int c = 0; c < 5; ++c) CHECK(eight.next() == c);
      CHECK(eight.next() == 5 + cycle % 3);
    }
    eight.reset();
    for (int i = 0; i < 5; ++i) CHECK(eight.next() == i);
    CHECK(eight.next() == 5);
    std::cout << "PASS all 5 critical ToF channels sampled before one optional direction\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
