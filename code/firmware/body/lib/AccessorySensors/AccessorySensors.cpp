#include "AccessorySensors.h"
#if defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER
namespace desk_robot {
bool AccessorySensors::mux(std::uint8_t address, std::uint8_t mask) {
  wire_->beginTransmission(address);
  return wire_->write(mask) == 1 && wire_->endTransmission(true) == 0;
}
bool AccessorySensors::select(std::uint8_t lane) {
  if (lane >= 8 || !mux_present_) return false;
  return mux(0x70, 0) && mux(0x71, static_cast<std::uint8_t>(1U << lane));
}
bool AccessorySensors::close() { return mux(0x71, 0); }
bool AccessorySensors::probe(std::uint8_t address) {
  wire_->beginTransmission(address);
  return wire_->endTransmission(true) == 0;
}
bool AccessorySensors::read(std::uint8_t address, std::uint8_t reg,
                             std::uint8_t* dest, std::uint8_t count) {
  if (!dest || !count || count > 16) return false;
  wire_->beginTransmission(address);
  if (wire_->write(reg) != 1 || wire_->endTransmission(false) != 0)
    return false;
  if (wire_->requestFrom(address, static_cast<std::size_t>(count), true) != count)
    return false;
  for (std::uint8_t i = 0; i < count; ++i) {
    if (wire_->available() < 1) return false;
    const int value = wire_->read();
    if (value < 0) return false;
    dest[i] = static_cast<std::uint8_t>(value);
  }
  return true;
}
bool AccessorySensors::read16(std::uint8_t address, std::uint8_t reg,
                               std::uint16_t& result) {
  std::uint8_t bytes[2]{};
  if (!read(address, reg, bytes, 2)) return false;
  result = static_cast<std::uint16_t>((bytes[0] << 8) | bytes[1]);
  return true;
}
bool AccessorySensors::write8(std::uint8_t address, std::uint8_t reg,
                               std::uint8_t value) {
  wire_->beginTransmission(address);
  const bool ok = wire_->write(reg) == 1 && wire_->write(value) == 1;
  return ok && wire_->endTransmission(true) == 0;
}
bool AccessorySensors::write16(std::uint8_t address, std::uint8_t reg,
                                std::uint16_t value) {
  wire_->beginTransmission(address);
  const bool ok = wire_->write(reg) == 1 &&
                  wire_->write(static_cast<std::uint8_t>(value >> 8)) == 1 &&
                  wire_->write(static_cast<std::uint8_t>(value)) == 1;
  return ok && wire_->endTransmission(true) == 0;
}
bool AccessorySensors::write_command(std::uint8_t address, std::uint8_t cmd) {
  wire_->beginTransmission(address);
  return wire_->write(cmd) == 1 && wire_->endTransmission(true) == 0;
}
bool AccessorySensors::begin(TwoWire& wire) {
  wire_ = &wire;
  wire_->beginTransmission(0x71);
  mux_present_ = wire_->endTransmission(true) == 0;
  data_ = AccessoryReadings{};
  next_lane_ = 1;
  started_ = false;
  sht_pending_ = ads_pending_ = false;
  gesture_.reset();
  gesture_collecting_ = false;
  if (!mux_present_) return false;
  // Validate APDS9960 manufacturer ID before enabling low-level proximity.
  if (select(1)) {
    std::uint8_t id = 0;
    // SparkFun defaults, adjusted without the blocking readGesture loop.
    // The device must report a recognized ID before enabling optical LEDs.
    const bool recognized =
        read(0x39, 0x92, &id, 1) && (id == 0xAB || id == 0x9C);
    data_.proximity.present = recognized &&
        write8(0x39, 0x80, 0x00) &&  // power off for configuration
        write8(0x39, 0x83, 0xFF) &&  // minimal wait interval
        write8(0x39, 0x8E, 0x89) &&  // proximity pulses
        write8(0x39, 0xA0, 40) &&    // gesture entry threshold
        write8(0x39, 0xA1, 30) &&    // gesture exit threshold
        write8(0x39, 0xA2, 0x40) &&  // FIFO threshold config
        write8(0x39, 0xA3, 0x20) &&  // 2x gesture gain, no extra LED boost
        write8(0x39, 0xA6, 0x89) &&  // gesture pulse
        write8(0x39, 0xAA, 0x00) &&  // all four directions enabled
        write8(0x39, 0xAB, 0x01) &&  // gesture mode, no IRQ
        write8(0x39, 0x80, 0x4D);    // PON + WEN + PEN + GEN
    data_.proximity.gesture_decoder_available = data_.proximity.present;
  }
  if (!close()) return false;
  // Probe only. No unverified output pin or high-power peripheral is enabled.
  if (select(2)) data_.force.present = probe(0x48);
  if (!close()) return false;
  if (select(3)) data_.climate.present = probe(0x44);
  if (!close()) return false;
  if (select(4)) {
    std::uint16_t manufacturer = 0;
    data_.gauge.monitor_present =
        read16(0x40, 0xFE, manufacturer) && manufacturer == 0x5449;
    data_.gauge.fuel_present = probe(0x36);
  }
  if (!close()) return false;
  for (std::uint8_t i = 0; i < 3; ++i) {
    const std::uint8_t lane = i == 0 ? 1 : i == 1 ? 6 : 7;
    if (select(lane)) data_.angle[i].present = probe(0x36);
    if (!close()) return false;
  }
  return true;
}
void AccessorySensors::angle(std::uint8_t index, std::uint32_t now_ms) {
  auto& a = data_.angle[index];
  if (!a.present) return;
  std::uint8_t status = 0;
  std::uint16_t raw = 0;
  a.valid = read(0x36, 0x0B, &status, 1) &&
            read16(0x36, 0x0C, raw);
  a.magnet_status = status & 0x38U;
  a.angle = raw & 0x0fffU;
  a.valid = a.valid && (a.magnet_status & 0x38U) == 0x20U;
  if (a.valid) a.at_ms = now_ms;
  // Angle alone is NOT travelled distance or traction calibration.
}
void AccessorySensors::gesture_fifo(std::uint32_t now_ms) {
  auto& p = data_.proximity;
  if (!p.gesture_decoder_available) return;
  std::uint8_t state = 0;
  if (!read(0x39, 0xAF, &state, 1)) { gesture_.reset(); gesture_collecting_ = false; return; }
  if (state & 0x02U) { // gesture FIFO overrun is not a real gesture event
    gesture_.reset();
    gesture_collecting_ = false;
    return;
  }
  if ((state & 0x01U) == 0) {
    if (gesture_collecting_) {
      const auto result = gesture_.finish();
      if (result != 0) {
        p.gesture_direction = result;
        ++p.gesture_events;
        p.at_ms = now_ms;
      }
      gesture_collecting_ = false;
    }
    return;
  }
  if (gesture_collecting_ && now_ms - gesture_started_ms_ > 700U) {
    gesture_.reset();
    gesture_collecting_ = false;
    return;
  }
  std::uint8_t available = 0;
  if (!read(0x39, 0xAE, &available, 1)) return;
  const std::uint8_t n = available > 4 ? 4 : available;
  if (!n) return;
  std::uint8_t records[16]{};
  // Only up to four (U,D,L,R) quads per pass, never SparkFun's
  // long repeated I2C loop or a delayed safety/cliff refresh.
  if (!read(0x39, 0xFC, records, n * 4)) {
    gesture_.reset();
    gesture_collecting_ = false;
    return;
  }
  if (!gesture_collecting_) {
    gesture_collecting_ = true;
    gesture_started_ms_ = now_ms;
    gesture_.reset();
  }
  for (std::uint8_t i = 0; i < n; ++i)
    gesture_.push(records[i * 4], records[i * 4 + 1],
                  records[i * 4 + 2], records[i * 4 + 3]);
}

void AccessorySensors::gesture_proximity(std::uint32_t now_ms) {
  auto& p = data_.proximity;
  if (p.present) {
    std::uint8_t raw = 0;
    p.valid = read(0x39, 0x9C, &raw, 1);
    if (p.valid) { p.raw = raw; p.at_ms = now_ms; }
    gesture_fifo(now_ms);
  }
  angle(0, now_ms);
}
void AccessorySensors::force(std::uint32_t now_ms) {
  auto& f = data_.force;
  if (!f.present) return;
  if (!ads_pending_) {
    const std::uint16_t config = ads_channel_ == 0 ? 0xC383U : 0xD383U;
    ads_pending_ = write16(0x48, 0x01, config);
    ads_started_ = now_ms;
    return;
  }
  if (now_ms - ads_started_ < 9U) return; // nonblocking ADS1115 128SPS
  std::uint16_t value = 0;
  const bool fresh = read16(0x48, 0x00, value);
  if (fresh) {
    f.adc[ads_channel_] = static_cast<std::int16_t>(value);
    f.valid_mask |= static_cast<std::uint8_t>(1U << ads_channel_);
    f.at_ms = now_ms;
  } else {
    f.valid_mask &= static_cast<std::uint8_t>(~(1U << ads_channel_));
  }
  f.valid = f.valid_mask == 3U;
  ads_channel_ ^= 1U;
  ads_pending_ = false;
  // FSR-to-force and grasp confidence still require measured mechanical tuning.
}
void AccessorySensors::climate(std::uint32_t now_ms) {
  auto& c = data_.climate;
  if (!c.present) return;
  if (!sht_pending_) {
    sht_pending_ = write_command(0x44, 0xFD); // highest precision, no clock stretch
    sht_started_ = now_ms;
    return;
  }
  if (now_ms - sht_started_ < 12U) return;
  std::uint8_t b[6]{};
  // SHT4x data read has no register pointer after a measurement command.
  c.valid = wire_->requestFrom(static_cast<std::uint8_t>(0x44),
                               static_cast<std::size_t>(6), true) == 6;
  for (int i = 0; i < 6 && c.valid; ++i) {
    if (wire_->available() < 1) c.valid = false;
    else { const int v = wire_->read(); if (v < 0) c.valid = false;
           else b[i] = static_cast<std::uint8_t>(v); }
  }
  c.valid = c.valid && sensirion_crc(b, 2) == b[2] &&
            sensirion_crc(b + 3, 2) == b[5];
  if (c.valid) {
    const auto t = static_cast<std::uint16_t>((b[0] << 8) | b[1]);
    const auto h = static_cast<std::uint16_t>((b[3] << 8) | b[4]);
    c.temp_centi = sht_temp_centi(t);
    c.humidity_centi = sht_humidity_centi(h);
    c.at_ms = now_ms;
  }
  sht_pending_ = false;
}
void AccessorySensors::power(std::uint32_t now_ms) {
  auto& g = data_.gauge;
  if (g.fuel_present) {
    std::uint16_t cell = 0, state_of_charge = 0;
    g.fuel_valid = read16(0x36, 0x02, cell) &&
                   read16(0x36, 0x04, state_of_charge);
    if (g.fuel_valid) {
      g.cell_mv = max17048_cell_mv(cell);
      g.soc_centi = max17048_soc_centi(state_of_charge);
      g.fuel_valid = g.cell_mv >= 2500 && g.cell_mv <= 4500 &&
                     g.soc_centi <= 10000;
    }
  }
  if (g.monitor_present) {
    std::uint16_t bus = 0, shunt = 0;
    g.monitor_valid = read16(0x40, 0x02, bus) &&
                      read16(0x40, 0x01, shunt);
    if (g.monitor_valid) {
      g.bus_mv = ina226_bus_mv(bus);
      g.shunt_uv = ina226_shunt_uv(static_cast<std::int16_t>(shunt));
    }
  }
  if (g.fuel_valid || g.monitor_valid) g.at_ms = now_ms;
  // Never infer amps from shunt voltage without a measured, rated shunt.
}
void AccessorySensors::poll(std::uint32_t now_ms) {
  if (!mux_present_ || (started_ && now_ms - last_ms_ < 12U)) return;
  started_ = true;
  last_ms_ = now_ms;
  const std::uint8_t lane = next_lane_;
  next_lane_ = lane >= 7 ? 1 : lane + 1;
  if (!select(lane)) { close(); return; }
  switch (lane) {
    case 1: gesture_proximity(now_ms); break;
    case 2: force(now_ms); break;
    case 3: climate(now_ms); break;
    case 4: power(now_ms); break;
    case 6: angle(1, now_ms); break;
    case 7: angle(2, now_ms); break;
    default: break;
  }
  if (!close()) {
    // 0x70 ToF owner will also fail closed if this mux cannot quiesce.
    data_.climate.valid = data_.force.valid =
      data_.proximity.valid = data_.gauge.fuel_valid =
      data_.gauge.monitor_valid = false;
    for (auto& sample : data_.angle) sample.valid = false;
  }
}
} // namespace desk_robot
#endif
