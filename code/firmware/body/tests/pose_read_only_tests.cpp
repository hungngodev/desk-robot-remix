#include "BodyControl.h"

#include <cstdint>
#include <stdexcept>
#include <string>

namespace {
void check(bool condition) {
  if (!condition) throw std::runtime_error("pose read-only contract failed");
}

std::string request(desk_robot::BodyControl& body,
                    desk_robot::LineReceiver& receiver,
                    const std::string& line, std::uint32_t now_ms,
                    std::uint64_t sample_us) {
  char reply[desk_robot::kReplyCapacity]{};
  bool complete = false;
  for (char byte : line)
    if (receiver.feed(byte, now_ms, body, reply, sizeof(reply), sample_us))
      complete = true;
  check(complete);
  return reply;
}

void verify() {
  desk_robot::BodyControl body;
  desk_robot::LineReceiver head;
  check(request(body, head, "pose\r\n", 10, 100000) ==
        "ERR pose clock_or_sequence_unavailable");
  body.set_boot_epoch(42);
  const std::string expected =
      "{\"v\":1,\"body_boot\":42,\"origin\":0,\"seq\":1,"
      "\"sample_us\":100001,\"x_mm\":0,\"y_mm\":0,"
      "\"yaw_mrad\":0,\"quality\":\"unavailable\"}";
  const auto first = request(body, head, "pose\r\n", 10, 100001);
  check(first == expected);
  check(first.size() < 180);
  check(!body.state().armed && body.state().left == 0 && body.state().right == 0);
  check(request(body, head, "pose\r\n", 10, 100001) ==
        "ERR pose clock_or_sequence_unavailable");
  check(request(body, head, "pose\r\n", 11, 100000) ==
        "ERR pose clock_or_sequence_unavailable");
  check(request(body, head, "pose extra\r\n", 11, 100002) ==
        "ERR pose bad_arguments");
  check(request(body, head, "pose v=2\r\n", 11, 100002) ==
        "ERR pose bad_arguments");
  check(request(body, head, "pose\r\n", 11, 100002).find("\"seq\":2") !=
        std::string::npos);
  check(request(body, head, "arm\r\n", 12, 100003) == "OK arm");
  check(request(body, head, "drive 20 20 250\r\n", 13, 100004).find("OK drive") == 0);
  const auto left = body.state().left;
  const auto right = body.state().right;
  check(request(body, head, "pose\r\n", 14, 100005).find(
      "\"quality\":\"unavailable\"") != std::string::npos);
  check(body.state().armed && body.state().left == left &&
        body.state().right == right);
  // A pose request must NOT refresh the 500 ms remote control watchdog.
  check(request(body, head, "pose\r\n", 514, 600005).find(
      "\"quality\":\"unavailable\"") != std::string::npos);
  check(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0);
  check(request(body, head, "stop\r\n", 515, 600006) == "OK stop");
  body.set_boot_epoch(99);
  const auto reboot = request(body, head, "pose\r\n", 1, 8);
  check(reboot.find("\"body_boot\":99") != std::string::npos);
  check(reboot.find("\"seq\":1") != std::string::npos);
  check(reboot.find("\"sample_us\":8") != std::string::npos);
  // Invalid times never become a recent body observation.
  check(request(body, head, "pose\r\n", 2, 9007199254740992ULL) ==
        "ERR pose clock_or_sequence_unavailable");
  // Reassigning the SAME boot identity cannot reset its sequence fence.
  body.set_boot_epoch(99);
  check(request(body, head, "pose\r\n", 3, 9).find("\"seq\":2") !=
        std::string::npos);

}

// Heavy read-only polling and rejected UART input must not turn into either a
// remote-control keepalive or an apparent new measured wheel observation.
void verify_poll_flood_and_malformed_frames() {
  desk_robot::BodyControl body;
  desk_robot::LineReceiver receiver;
  body.set_boot_epoch(73);
  check(request(body, receiver, "arm\r\n", 10, 0) == "OK arm");
  check(request(body, receiver, "drive 15 -15 250\r\n", 11, 0)
            .find("OK drive") == 0);

  std::uint32_t sequence = 0;
  for (std::uint32_t now = 12; now <= 612; now += 24) {
    const auto response = request(
        body, receiver, "pose\r\n", now,
        static_cast<std::uint64_t>(now) * 1000ULL);
    check(response.find("\"seq\":" + std::to_string(++sequence) + ",") !=
          std::string::npos);
    check(response.find("\"origin\":0") != std::string::npos);
    check(response.find("\"quality\":\"unavailable\"") != std::string::npos);
    if (now >= 276)
      check(body.state().left == 0 && body.state().right == 0);
    if (now >= 516) check(!body.state().armed);
  }
  check(!body.state().armed);
  check(request(body, receiver, "pose v=2\r\n", 650, 650000) ==
        "ERR pose bad_arguments");
  check(request(body, receiver, "pose\rjunk\n", 650, 650000) ==
        "ERR input invalid_ascii");
  check(request(body, receiver,
                "pose" + std::string(desk_robot::kMaxLineLength + 1, 'x') +
                    "\r\n", 650, 650000) ==
        "ERR input line_too_long");
  const auto next = request(body, receiver, "pose\r\n", 650, 650000);
  check(next.find("\"seq\":" + std::to_string(sequence + 1) + ",") !=
        std::string::npos);
  check(next.find("\"quality\":\"unavailable\"") != std::string::npos);
  check(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0);
}
// A failed reply serialization must not invent a missing sample in the
// downstream sequence, even if a future caller uses a smaller UART buffer.
void verify_pose_capacity_failure_preserves_clock_and_sequence() {
  desk_robot::BodyControl body;
  desk_robot::LineReceiver receiver;
  body.set_boot_epoch(88);
  char small[48]{};
  body.execute("pose", 4, 1, small, sizeof(small), false, 111111);
  check(std::string(small) == "ERR pose reply_capacity");
  const auto first = request(body, receiver, "pose\r\n", 1, 111111);
  check(first.find("\"seq\":1,") != std::string::npos);
  check(first.find("\"sample_us\":111111,") != std::string::npos);

  // C99 snprintf permits capacity zero without writing to the destination.
  // A failed zero-size response must not update sample provenance either.
  char no_space[1] = {'X'};
  body.execute("pose", 4, 2, no_space, 0, false, 111112);
  check(no_space[0] == 'X');
  const auto next = request(body, receiver, "pose\r\n", 2, 111112);
  check(next.find("\"seq\":2,") != std::string::npos);
  check(next.find("\"sample_us\":111112,") != std::string::npos);
  check(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0);
}
void verify_wheel_capture_stays_read_only() {
  desk_robot::BodyControl body;
  desk_robot::LineReceiver receiver;
  check(!body.configure_wheel_angle_capture(4000, 4000, 200, 80));
  body.set_boot_epoch(101);
  check(!body.configure_wheel_angle_capture(4000, 12000, 200, 80));
  check(body.configure_wheel_angle_capture(4000, 4000, 200, 80));
  check(!body.configure_wheel_angle_capture(4000, 4000, 200, 80));
  desk_robot::AccessoryReadings readings{};
  auto update = [](desk_robot::AngleRaw& a, std::uint16_t value,
                   std::uint32_t sequence, std::uint32_t at_ms) {
    a.present = a.valid = true;
    a.magnet_status = 0x20;
    a.angle = value;
    a.sample_seq = sequence;
    a.at_ms = at_ms;
  };
  update(readings.angle[1], 4000, 1, 100);
  update(readings.angle[2], 20, 1, 100);
  body.set_accessories(readings, 100);
  check(body.wheel_angle_capture(false).continuous() &&
        body.wheel_angle_capture(true).continuous());
  update(readings.angle[1], 12, 2, 150);
  update(readings.angle[2], 4080, 2, 150);
  body.set_accessories(readings, 150);
  check(body.wheel_angle_capture(false).angular_counts() == 108 &&
        body.wheel_angle_capture(true).angular_counts() == -36);
  body.set_accessories(readings, 160); // cached values are duplicates
  check(body.wheel_angle_capture(false).angular_counts() == 108);
  readings.angle[1].magnet_status = 0; // broken magnet cannot keep old ticks
  update(readings.angle[2], 4070, 3, 180);
  body.set_accessories(readings, 180);
  check(!body.wheel_angle_capture(false).continuous() &&
        body.wheel_angle_capture(true).angular_counts() == -46);
  update(readings.angle[1], 20, 4, 190);
  body.set_accessories(readings, 190); // new baseline, no bridged travel
  check(body.wheel_angle_capture(false).continuous() &&
        body.wheel_angle_capture(false).angular_counts() == 0);
  update(readings.angle[1], 12, 2, 150); // old acquisition replay
  body.set_accessories(readings, 195);
  check(!body.wheel_angle_capture(false).continuous());
  // No raw shaft reading may promote the UART pose, renew a watchdog or ARM.
  check(request(body, receiver, "pose\r\n", 196, 196000).find(
      "\"quality\":\"unavailable\"") != std::string::npos);
  check(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0);
  body.set_boot_epoch(102); // no prior shaft origin survives a reboot
  check(!body.wheel_angle_capture(false).continuous() &&
        !body.wheel_angle_capture(true).continuous());
  check(!body.configure_wheel_angle_capture(0, 4000, 200, 80));
  check(body.configure_wheel_angle_capture(4000, 4000, 200, 80));
}
void verify_angle_qualification_telemetry() {
  desk_robot::BodyControl body;
  desk_robot::LineReceiver receiver;
  body.set_boot_epoch(123);
  desk_robot::AccessoryReadings readings{};
  auto& nose = readings.angle[0];
  auto& left = readings.angle[1];
  auto& right = readings.angle[2];
  nose.present = nose.valid = true;
  nose.magnet_status = 0x20;
  nose.angle = 100;
  nose.sample_seq = 1;
  nose.at_ms = 970;
  left.present = left.valid = true;
  left.magnet_status = 0x20;
  left.angle = 4094;
  left.sample_seq = 7;
  left.at_ms = 980;
  right.present = right.valid = true;
  right.magnet_status = 0x20;
  right.angle = 12;
  right.sample_seq = 9;
  right.at_ms = 990;
  body.set_accessories(readings, 1000);
  auto reply = request(body, receiver, "aux\r\n", 1000, 0);
  check(reply.find("\"seq\":[1,7,9]") != std::string::npos);
  check(reply.find("\"age_ms\":[30,20,10]") != std::string::npos);
  check(reply.find("\"boot_id\":123,\"wheel_travel_qualified\":false") != std::string::npos);
  check(reply.find("\"valid_mask\":7") != std::string::npos);
  check(reply.size() < desk_robot::kReplyCapacity);
  check(!body.state().armed);
  // Cached conversions age; AUX reads cannot change the AS5600 identity.
  reply = request(body, receiver, "aux\r\n", 1100, 0);
  check(reply.find("\"seq\":[1,7,9]") != std::string::npos);
  check(reply.find("\"age_ms\":[130,120,110]") != std::string::npos);
  left.valid = false; // A failed magnet or mux must not look valid.
  body.set_accessories(readings, 1120);
  reply = request(body, receiver, "aux\r\n", 1120, 0);
  check(reply.find("\"valid_mask\":5") != std::string::npos);
  check(reply.find("\"seq\":[1,7,9]") != std::string::npos);
  // At timestamp zero after millis rollover, nonzero source sequence
  // differentiates a real conversion from an uninitialized sample.
  body.set_boot_epoch(124);
  nose.at_ms = 0;
  nose.sample_seq = 2;
  nose.valid = true;
  right.at_ms = 0xfffffff0U;
  right.sample_seq = 10;
  right.valid = true;
  left.sample_seq = 0;
  body.set_accessories(readings, 20);
  reply = request(body, receiver, "aux\r\n", 20, 0);
  check(reply.find("\"seq\":[2,0,10]") != std::string::npos);
  check(reply.find("\"age_ms\":[20,0,36]") != std::string::npos);
  check(reply.find("\"boot_id\":124,\"wheel_travel_qualified\":false") != std::string::npos);
  check(!body.state().armed && body.state().left == 0 && body.state().right == 0);
}
void verify_paired_wheel_acquisitions() {
  desk_robot::BodyControl body;
  desk_robot::LineReceiver receiver;
  check(!body.configure_wheel_pair_skew(25));
  body.set_boot_epoch(201);
  check(body.configure_wheel_angle_capture(4000, 4000, 200, 150));
  check(!body.configure_wheel_pair_skew(0));
  check(!body.configure_wheel_pair_skew(101));
  check(body.configure_wheel_pair_skew(25));
  check(!body.configure_wheel_pair_skew(25));
  desk_robot::AccessoryReadings reads{};
  auto update = [](desk_robot::AngleRaw& a, std::uint16_t angle,
                   std::uint32_t seq, std::uint32_t ms) {
    a.present = a.valid = true;
    a.magnet_status = 0x20;
    a.angle = angle; a.sample_seq = seq; a.at_ms = ms;
  };
  update(reads.angle[1], 4000, 1, 100);
  update(reads.angle[2], 20, 1, 112);
  body.set_accessories(reads, 112);
  check(!body.wheel_pair_receipt().valid);
  update(reads.angle[1], 4010, 2, 200);
  body.set_accessories(reads, 200);
  check(!body.wheel_pair_receipt().valid);
  update(reads.angle[2], 10, 2, 212);
  body.set_accessories(reads, 212);
  const auto first = body.wheel_pair_receipt();
  check(first.valid && first.pair_seq == 1 && first.segment == 1);
  check(first.left_delta == 10 && first.right_delta == -10);
  check(first.left_seq == 2 && first.right_seq == 2);
  check(first.skew_ms == 12 && first.left_ms == 200 && first.right_ms == 212);
  body.set_accessories(reads, 213); // same read cannot advance pair sequence
  check(body.wheel_pair_receipt().pair_seq == 1);
  update(reads.angle[1], 4020, 3, 300);
  body.set_accessories(reads, 300);
  check(body.wheel_pair_receipt().valid); // latest confirmed pair is unchanged
  body.set_accessories(reads, 326); // unmatched one-leg sample times out
  check(!body.wheel_pair_receipt().valid);
  check(!body.wheel_angle_capture(false).continuous());
  check(!body.wheel_angle_capture(true).continuous());
  update(reads.angle[1], 4030, 4, 340);
  update(reads.angle[2], 5, 3, 352);
  body.set_accessories(reads, 352); // new local segment
  update(reads.angle[1], 4040, 5, 410);
  body.set_accessories(reads, 410);
  update(reads.angle[2], 4090, 4, 422);
  body.set_accessories(reads, 422);
  check(body.wheel_pair_receipt().valid &&
        body.wheel_pair_receipt().pair_seq == 2 &&
        body.wheel_pair_receipt().segment == 2);
  reads.angle[1].magnet_status = 0; // fault on any wheel revokes pair
  body.set_accessories(reads, 425);
  check(!body.wheel_pair_receipt().valid);
  check(request(body, receiver, "pose\r\n", 425, 425000).find(
      "\"quality\":\"unavailable\"") != std::string::npos);
  check(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0);
  body.set_boot_epoch(202);
  check(!body.wheel_pair_receipt().valid);
  check(!body.configure_wheel_pair_skew(20));
  check(body.configure_wheel_angle_capture(4000, 4000, 200, 150));
  check(body.configure_wheel_pair_skew(25));
  // The first pair after a new boot cannot reuse old body sequence/segment.
  update(reads.angle[1], 4090, 1, 0xfffffff0U);
  update(reads.angle[2], 10, 1, 0);
  body.set_accessories(reads, 0);
  update(reads.angle[1], 4093, 2, 0x20U);
  body.set_accessories(reads, 0x20U);
  update(reads.angle[2], 8, 2, 0x30U);
  body.set_accessories(reads, 0x30U);
  check(body.wheel_pair_receipt().valid &&
        body.wheel_pair_receipt().pair_seq == 1 &&
        body.wheel_pair_receipt().left_delta == 3 &&
        body.wheel_pair_receipt().right_delta == -2 &&
        body.wheel_pair_receipt().skew_ms == 16);
  check(!body.state().armed);
}
void verify_imu_yaw_never_promotes_pose() {
  desk_robot::BodyControl body;
  desk_robot::LineReceiver receiver;
  auto limits = desk_robot::ImuYawCapture::Calibration{};
  limits.axis = 2;
  limits.sign = 1;
  limits.max_rate_raw = 500;
  limits.bias_uncertainty_raw = 20;
  limits.scale_error_ppm = 20000;
  limits.accel_norm_min_raw = 12000;
  limits.accel_norm_max_raw = 20000;
  limits.temp_min_raw = -1000;
  limits.temp_max_raw = 1000;
  limits.max_gap_ms = 200;
  limits.max_age_ms = 150;
  limits.max_yaw_error_urad = 500000;
  check(!body.configure_imu_yaw_capture(limits));
  body.set_boot_epoch(302);
  check(!body.configure_imu_yaw_capture(limits)); // unrecognized IMU
  body.set_imu_identity(4, 0x68, 0);
  check(body.configure_imu_yaw_capture(limits));
  check(!body.configure_imu_yaw_capture(limits));
  desk_robot::BerryReading r{};
  r.model = desk_robot::BerryModel::Mpu6050;
  r.valid = r.low_g_status_valid = true;
  r.accel[2] = 16384;
  r.gyro[2] = 131;
  r.temperature_raw = 100;
  r.at_ms = 100;
  body.set_imu(r);
  check(body.imu_yaw_capture().continuous());
  r.at_ms = 200;
  body.set_imu(r);
  check(body.imu_yaw_capture().yaw_urad() == 1745);
  check(body.imu_yaw_capture().fresh(200));
  check(!body.imu_yaw_capture().fresh(400));
  check(request(body, receiver, "pose\r\n", 210, 210000).find(
      "\"quality\":\"unavailable\"") != std::string::npos);
  r.at_ms = 300;
  r.low_g_irq = true;
  body.set_imu(r);
  check(!body.imu_yaw_capture().continuous()); // pickup/low-g breaks origin
  check(!body.state().armed);
  body.set_boot_epoch(303);
  check(!body.imu_yaw_capture().continuous());
  check(!body.configure_wheel_pair_skew(25));
  check(body.configure_imu_yaw_capture(limits)); // explicitly new boot-only cal
  check(request(body, receiver, "pose\r\n", 2, 100).find(
      "\"quality\":\"unavailable\"") != std::string::npos);
}
}  // namespace

int main() {
  verify();
  verify_poll_flood_and_malformed_frames();
  verify_pose_capacity_failure_preserves_clock_and_sequence();
  verify_wheel_capture_stays_read_only();
  verify_angle_qualification_telemetry();
  verify_paired_wheel_acquisitions();
  verify_imu_yaw_never_promotes_pose();
  return 0;
}
