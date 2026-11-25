#include "camera_frame_bounds.hpp"

#include <cassert>
#include <initializer_list>
#include <limits>

int main() {
    using desk_robot::ValidRgb565Frame;
    constexpr auto max = std::numeric_limits<std::size_t>::max();
    static_assert(ValidRgb565Frame(320, 240, 153600));
    static_assert(ValidRgb565Frame(640, 480, 614400));
    static_assert(ValidRgb565Frame(480, 640, 614400));
    static_assert(!ValidRgb565Frame(0, 240, 0));
    static_assert(!ValidRgb565Frame(320, 0, 0));
    static_assert(!ValidRgb565Frame(max, max, max));
    static_assert(!ValidRgb565Frame(640, 640, 819200));
    for (std::size_t bytes : {0u, 153599u, 153601u, 614400u}) {
        assert(!ValidRgb565Frame(320, 240, bytes));
    }
    assert(!ValidRgb565Frame(641, 1, 1282));
    assert(!ValidRgb565Frame(1, 641, 1282));

    // Independent multiplication is safe over this bounded test domain.
    // Exercise every edge pair, including nonstandard aspect ratios, and
    // verify exact lengths rather than merely a few named resolutions.
    for (std::size_t width = 0; width <= 641; ++width) {
        for (std::size_t height = 0; height <= 641; ++height) {
            const auto bytes = width * height * 2;
            const bool expected = width != 0 && height != 0 &&
                                  width <= 640 && height <= 640 && bytes <= 614400;
            assert(ValidRgb565Frame(width, height, bytes) == expected);
            if (expected) {
                assert(!ValidRgb565Frame(width, height, bytes - 1));
                assert(!ValidRgb565Frame(width, height, bytes + 1));
            }
        }
    }
    assert(!ValidRgb565Frame(max, 1, max));
    assert(!ValidRgb565Frame(1, max, max));
    assert(!ValidRgb565Frame(1, 1, max));
}
