#include "AccessorySensors.h"
#include "../../include/MuxWrite.h"
#ifndef DESK_ROBOT_PACK_SHUNT_MOHM
#define DESK_ROBOT_PACK_SHUNT_MOHM 0
#endif
#if DESK_ROBOT_PACK_SHUNT_MOHM != 0 && DESK_ROBOT_PACK_SHUNT_MOHM != 5
#error Exact pack shunt must be source-qualified 5 mOhm or OFF
#endif
#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
namespace desk_robot {
bool AccessorySensors::bus_available() {
  // Once a line is observed held, stop this entire polling slice even if
  // the slave releases it before the next helper. Only the body loop owns
  // recovery and must get control back before additional Wire transactions.
  if (!bus_blocked_ && bus_accessible_ && !bus_accessible_())
    bus_blocked_ = true;
  return !bus_blocked_;
}
bool AccessorySensors::mux(std::uint8_t address, std::uint8_t mask) {
  if (!bus_available()) return false;
  const auto result = write_mux_mask(*wire_, address, mask);
  return bus_available() && result.ok();
}
bool AccessorySensors::verified_mux(std::uint8_t address, std::uint8_t mask) {
  // TI TCA9548A SCPS207H: a write ACK is not a verified channel change.
  // Read the control register after STOP, including on mux close. Otherwise
  // a stuck optional lane can leave cached dock/seat evidence appearing live.
  if (!mux(address, mask)) return false;
  const auto received = wire_->requestFrom(address, static_cast<std::size_t>(1), true);
  if (!bus_available() || received != 1 || wire_->available() < 1) return false;
  return wire_->read() == mask;
}
void AccessorySensors::set_nfc_collection_enabled(bool enabled,
                                                  std::uint32_t now_ms) {
  if (enabled == nfc_collection_enabled_) return;
  nfc_collection_enabled_ = enabled;
  if (!enabled) {
    nfc_pending_probe_ = false;
    nfc_stage_ = NfcStage::Disabled;
    nfc_phase_at_ms_ = nfc_last_scan_at_ms_ = 0;
    data_.nfc = NfcRaw{};
    return;
  }
  nfc_pending_probe_ = true;
  nfc_stage_ = NfcStage::Disabled;
  nfc_phase_at_ms_ = 0;
  nfc_last_scan_at_ms_ = now_ms;
}

void AccessorySensors::reset_nfc_protocol(std::uint32_t now_ms) {
  if (!nfc_collection_enabled_) {
    nfc_pending_probe_ = false;
    nfc_stage_ = NfcStage::Disabled;
    nfc_phase_at_ms_ = nfc_last_scan_at_ms_ = 0;
    data_.nfc = NfcRaw{};
    return;
  }
  data_.nfc.transport_failed();
  if (nfc_stage_ != NfcStage::Disabled) {
    nfc_stage_ = NfcStage::StartSam;
    nfc_phase_at_ms_ = 0;
    nfc_last_scan_at_ms_ = now_ms;
  }
}

void AccessorySensors::invalidate_cached() {
  // One failed shared-bus/mux transfer invalidates ALL cached optional
  // evidence. A valid GPIOA sample can return only after fresh acquisition.
  data_.barometer.valid = false;
  data_.climate.valid = data_.force.valid =
    data_.proximity.valid = data_.gauge.fuel_valid =
    data_.gauge.monitor_valid = data_.dock.valid = false;
  data_.gauge.pack_current_valid = false;
  // Reset any in-flight PN532 command/response phase while preserving Disabled.
  reset_nfc_protocol(last_ms_);
  // Invalidate the complete ADS1115 acquisition pair. Otherwise a single
  // post-fault conversion can combine with the other channel's stale bit.
  data_.force.valid_mask = 0;
  ads_pending_ = false;
  // A single-shot climate result started before lost mux isolation is
  // no longer a fresh acquisition. Command a new conversion on recovery.
  sht_pending_ = false;
  data_.optional_inputs.valid = false;
  gesture_.invalidate();
#if DESK_ROBOT_ENABLE_HAPTIC
  haptic_.fault();
  haptic_needs_low_ = true;  // retry deassertion after a bus/mux fault
#endif
  for (auto& sample : data_.angle) sample.valid = false;
}
bool AccessorySensors::select(std::uint8_t lane) {
  if (lane >= 8 || !mux_present_) return false;
  return verified_mux(0x70, 0) &&
         verified_mux(0x71, static_cast<std::uint8_t>(1U << lane));
}
bool AccessorySensors::close() { return verified_mux(0x71, 0); }
bool AccessorySensors::probe(std::uint8_t address) {
  if (!bus_available()) return false;
  wire_->beginTransmission(address);
  const bool acknowledged = wire_->endTransmission(true) == 0;
  return bus_available() && acknowledged;
}
bool AccessorySensors::read(std::uint8_t address, std::uint8_t reg,
                             std::uint8_t* dest, std::uint8_t count) {
  if (!dest || !count || count > 16) return false;
  if (!bus_available()) return false;
  wire_->beginTransmission(address);
  const bool wrote = wire_->write(reg) == 1;
  // Always terminate a failed partial transmission with STOP. Otherwise a
  // rejected write may leave Wire in a transaction while the dock GPIOA
  // freshness gate thinks the optional controller simply vanished.
  const bool acknowledged = wire_->endTransmission(!wrote) == 0;
  if (!wrote || !acknowledged) {
    bus_available();  // STOP completed on a rejected pointer write.
    return false;
  }
  const auto received = wire_->requestFrom(address, static_cast<std::size_t>(count), true);
  if (!bus_available() || received != count) return false;
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
  if (!bus_available()) return false;
  wire_->beginTransmission(address);
  const bool wrote = wire_->write(reg) == 1 && wire_->write(value) == 1;
  const bool acknowledged = wire_->endTransmission(true) == 0;
  return bus_available() && wrote && acknowledged;
}
bool AccessorySensors::write16(std::uint8_t address, std::uint8_t reg,
                                std::uint16_t value) {
  if (!bus_available()) return false;
  wire_->beginTransmission(address);
  const bool wrote = wire_->write(reg) == 1 &&
                     wire_->write(static_cast<std::uint8_t>(value >> 8)) == 1 &&
                     wire_->write(static_cast<std::uint8_t>(value)) == 1;
  const bool acknowledged = wire_->endTransmission(true) == 0;
  return bus_available() && wrote && acknowledged;
}
bool AccessorySensors::write_command(std::uint8_t address, std::uint8_t cmd) {
  if (!bus_available()) return false;
  wire_->beginTransmission(address);
  const bool wrote = wire_->write(cmd) == 1;
  const bool acknowledged = wire_->endTransmission(true) == 0;
  return bus_available() && wrote && acknowledged;
}
bool AccessorySensors::begin(TwoWire& wire, bool (*bus_accessible)()) {
  wire_ = &wire;
  bus_accessible_ = bus_accessible;
  bus_blocked_ = false;
  mux_present_ = false;
  if (bus_available()) {
    wire_->beginTransmission(0x71);
    mux_present_ = wire_->endTransmission(true) == 0;
    bus_available();
  }
  data_ = AccessoryReadings{};
  mcp_ports_ = McpPortDirectionLock{};
#if DESK_ROBOT_ENABLE_HAPTIC
  haptic_.configure(false);
  haptic_needs_low_ = false;
#endif
  next_lane_ = 1;
  started_ = false;
  sht_pending_ = ads_pending_ = false;
  gesture_.restart();
  nfc_collection_enabled_ = false;
  nfc_pending_probe_ = false;
  nfc_stage_ = NfcStage::Disabled;
  nfc_phase_at_ms_ = nfc_last_scan_at_ms_ = 0;
  if (!mux_present_ || !bus_available()) return false;
  // A missing peripheral is optional; unverified mux isolation is not.
  const auto select_startup = [this](std::uint8_t lane) {
    if (select(lane)) return true;
    close();
    return false;
  };
  // Validate APDS9960 manufacturer ID before enabling low-level proximity.
  if (!select_startup(1)) return false;
  {
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
  if (!select_startup(2)) return false;
  data_.force.present = probe(0x48);
  if (!close()) return false;
  if (!select_startup(3)) return false;
  {
    data_.climate.present = probe(0x44);
    // User-owned BMP280 may be strapped to either 0x76 or 0x77.
    // Reject BME280 0x60 and random ACKs; keep SHT41 independent.
    for (const std::uint8_t addr : {static_cast<std::uint8_t>(0x76),
                                    static_cast<std::uint8_t>(0x77)}) {
      std::uint8_t chip = 0, coeff[24]{};
      if (read(addr, 0xD0, &chip, 1) && chip == 0x58 &&
          read(addr, 0x88, coeff, 12) &&
          read(addr, 0x94, coeff + 12, 12) &&
          bmp280_trim(coeff, bmp_trim_) &&
          write8(addr, 0xF5, 0xA0) && // 1-second standby, no IIR
          write8(addr, 0xF4, 0x27)) { // pressure/temp x1, normal
        data_.barometer.present = true;
        data_.barometer.address = addr;
        data_.barometer.chip_id = chip;
        break;
      }
    }
  }
  if (!close()) return false;
  if (!select_startup(4)) return false;
  {
    std::uint16_t manufacturer = 0;
    data_.gauge.monitor_present =
        read16(0x40, 0xFE, manufacturer) && manufacturer == 0x5449;
    // MAX17048/MAX17049 datasheet Rev 7, table 2: VERSION is 0x001x.
    // See also Zephyr drivers/fuel_gauge/max17048/max17048.c init check.
    // An address ACK alone is not identity (AS5600 also uses 0x36).
    // The family signature does not distinguish 1S from 2S hardware.
    std::uint16_t version = 0;
    data_.gauge.fuel_present =
        read16(0x36, 0x08, version) && (version & 0xFFF0U) == 0x0010U;
  }
  if (!close()) return false;
  // MCP23017 on accessory mux lane 5 only READS physical dock evidence.
  // GPA0/1: normally closed independent dock stop switches, HIGH when open.
  // GPA2: charger PGOOD open drain, LOW when input valid.
  // GPA3: charger CHG open drain, LOW when chip indicates charging.
  // This is not a charge enable. A broken switch alone cannot declare a
  // charging battery. Never connect raw 5V pad voltage to a 3.3V input.
  if (!select_startup(5)) return false;
  {
    data_.dock.present = probe(0x20) &&
        write8(0x20, 0x00, 0xFF) &&  // all GPIOA inputs
        write8(0x20, 0x0C, 0x0F);    // 3.3V pullups GPA0..3
    // GPIOB is a separate slow read-only optional input port. Moving reed
    // and PIR here keeps WROOM GPIO36/39 free for timer-capable dock IR.
    // Never make GPIOB validity a substitute for required GPIOA freshness.
    data_.optional_inputs.present = data_.dock.present &&
        write8(0x20, 0x01, 0xFF) && // all GPIOB inputs, no output drivers
        write8(0x20, 0x0D, 0x01);   // B0 reed pullup; B1 PIR externally biased
#if DESK_ROBOT_ENABLE_HAPTIC
    // MCP23017 BANK=0: GPB2 is an edge into an EXTERNALLY CURRENT-LIMITED,
    // hardware one-shot motor driver. The expander is not a watchdog.
    // Initialize the OLATB latch LOW before making GPB2 an output.
    // B0/B1 remain inputs for the reported reed and PIR sensors.
    if (data_.optional_inputs.present) {
      std::uint8_t latch = 0xff, direction = 0xff;
      const bool direction_written =
          write8(0x20, 0x15, 0x00) &&
          write8(0x20, 0x01, 0xFB);
      if (direction_written) mcp_ports_.expect_haptic_output();
      const bool configured = direction_written &&
          read(0x20, 0x15, &latch, 1) && latch == 0x00 &&
          read(0x20, 0x01, &direction, 1) && direction == 0xFB;
      haptic_.configure(configured);
      haptic_needs_low_ = !configured;
    }
#endif
    if (data_.dock.present && !verify_mcp_ports()) invalidate_cached();
    // PN532 acquisition is default-off and requires explicit consent; do not
    // probe or start the reader during boot before opt-in is granted.
  }
  if (!close()) return false;
  for (std::uint8_t i = 0; i < 3; ++i) {
    const std::uint8_t lane = i == 0 ? 1 : i == 1 ? 6 : 7;
    if (!select_startup(lane)) return false;
    data_.angle[i].present = probe(0x36);
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
  if (a.valid) {
    a.at_ms = now_ms;
    a.sample_seq = next_nonzero_sensor_sequence(a.sample_seq);
  }
  // Angle alone is NOT travelled distance or traction calibration.
}
void AccessorySensors::gesture_fifo(std::uint32_t now_ms) {
  auto& p = data_.proximity;
  if (!p.gesture_decoder_available) return;
  std::uint8_t state = 0, direction = 0;
  if (!read(0x39, 0xAF, &state, 1)) {
    gesture_.invalidate();
    return;
  }
  const auto action = gesture_.poll_status(state, now_ms, direction);
  if (action == GestureDecoder::PollAction::Clear) {
    // APDS9960 GCONF4 bit 2 clears FIFO, overflow and GVALID. GIEN and
    // GMODE stay zero, so the next session must enter on optical evidence.
    // A failed write leaves the decoder quarantined until clean idle.
    write8(0x39, 0xAB, 0x04);
    return;
  }
  if (direction != 0) {
    p.gesture_direction = direction;
    ++p.gesture_events;
    // A decoded gesture is not a new PDATA conversion.
  }
  if (action != GestureDecoder::PollAction::Read) return;
  std::uint8_t available = 0;
  if (!read(0x39, 0xAE, &available, 1) || available > 32U) {
    gesture_.invalidate();
    return;
  }
  const std::uint8_t n = available > 4 ? 4 : available;
  if (!n) return;
  std::uint8_t records[16]{};
  // Only up to four (U,D,L,R) quads per pass, never SparkFun's
  // long repeated I2C loop or a delayed safety/cliff refresh.
  if (!read(0x39, 0xFC, records, n * 4)) {
    gesture_.invalidate();
    return;
  }
  gesture_.begin_batch(now_ms);
  for (std::uint8_t i = 0; i < n; ++i)
    gesture_.push(records[i * 4], records[i * 4 + 1],
                  records[i * 4 + 2], records[i * 4 + 3]);
}

void AccessorySensors::gesture_proximity(std::uint32_t now_ms) {
  auto& p = data_.proximity;
  if (p.present) {
    std::uint8_t status = 0, raw = 0;
    p.valid = false;
    // APDS9960 STATUS.PVALID is cleared by reading PDATA. An ACK alone
    // does not establish a new proximity conversion (AV02-4191EN).
    if (!read(0x39, 0x93, &status, 1)) {
      gesture_.invalidate();
    } else if (apds_proximity_ready(status)) {
      if (!read(0x39, 0x9C, &raw, 1)) {
        gesture_.invalidate();
      } else {
        p.raw = raw;
        // Full-scale proximity cannot resolve distance or establish a new event.
        if (p.saturated()) {
          gesture_.invalidate();
        } else {
          p.valid = true;
          p.at_ms = now_ms;
        }
      }
    }
    // The gesture engine has its own GVALID and FIFO, even when PVALID is low.
    gesture_fifo(now_ms);
  }
  angle(0, now_ms);
}
void AccessorySensors::force(std::uint32_t now_ms) {
  auto& f = data_.force;
  if (!f.present) return;
  if (!ads_pending_) {
    const std::uint16_t config = ads_channel_ == 0 ? 0xC383U : 0xD383U;
    // TI ADS1115 single-shot mode ignores OS writes while a conversion is
    // running. After a timeout or bus fault, wait for idle before starting
    // a new conversion; never relabel the abandoned result as a new sample.
    std::uint16_t previous_config = 0;
    if (!read16(0x48, 0x01, previous_config) ||
        (previous_config & 0x8000U) == 0U) {
      f.valid = false;
      f.valid_mask = 0;
      return;
    }
    // Losing the ADC config write invalidates the ENTIRE two-channel
    // reading, even if the optional mux itself still works correctly.
    // Otherwise an old accepted pair survives indefinitely as fresh force.
    if (!write16(0x48, 0x01, config)) {
      f.valid = false;
      f.valid_mask = 0;
      ads_pending_ = false;
      return;
    }
    ads_pending_ = true;
    ads_started_ = now_ms;
    return;
  }
  // A completed single-shot ADC register can remain readable indefinitely.
  // After a delayed WROOM loop it describes OLD jaw force, not a new grasp
  // observation. Never stamp it with a current timestamp or fresh sequence.
  // A timeout on either channel retires the shared ADC's force evidence.
  // Retry the selected channel with a newly commanded conversion next visit.
  if (now_ms - ads_started_ >= 200U) {
    f.valid_mask = 0;
    f.valid = false;
    ads_pending_ = false;
    return;
  }
  if (now_ms - ads_started_ < 9U) return; // nonblocking ADS1115 128SPS
  std::uint16_t config = 0;
  const bool status_read = read16(0x48, 0x01, config);
  // Do not increment an acquisition sequence for a cached conversion register.
  // Config bit 15 (0x8000) is OS: zero means conversion in progress.
  // Retry on a later mux visit, bounded by the 200ms sample deadline.
  if (status_read && (config & 0x8000U) == 0U &&
      now_ms - ads_started_ < 200U) return;
  std::uint16_t value = 0;
  const bool conversion_matches = status_read &&
      ads1115_completed_for_channel(config, ads_channel_);
  const bool fresh = conversion_matches && read16(0x48, 0x00, value);
  if (!status_read || (conversion_matches && !fresh)) {
    // Both FSR channels share this ADC. A transport failure is not an
    // independent channel fault; require two new successful conversions.
    f.valid_mask = 0;
  // Conversion register codes 0x7fff and 0x8000 are signed full-scale
  // rails, not OS status bits. Reject them as unqualified FSR evidence.
  } else if (fresh && ads1115_force_from_raw(value, f.adc[ads_channel_])) {
    f.valid_mask |= static_cast<std::uint8_t>(1U << ads_channel_);
    // Timestamp conservatively at the start of the single shot, not the
    // later mux visit that retrieved its cached result.
    if (ads_channel_ == 0) {
      f.belly_sample_seq = next_nonzero_sensor_sequence(f.belly_sample_seq);
      f.belly_at_ms = ads_started_;
    } else if (ads_channel_ == 1) {
      f.jaw_sample_seq = next_nonzero_sensor_sequence(f.jaw_sample_seq);
      f.jaw_at_ms = ads_started_;
    }
    f.at_ms = ads_started_;
  } else {
    // A clipped or mismatched conversion is local to this channel. Keep
    // the other channel's raw value, validity and acquisition identity.
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
    // A rejected command is lost transport evidence, not a new conversion.
    if (!sht_pending_) c.valid = false;
    sht_started_ = now_ms;
    return;
  }
  // A completed SHT41 single-shot result can remain readable long after
  // the conversion that produced it. After a stalled WROOM loop that is old
  // environmental evidence, so never restamp it as a current acquisition.
  if (now_ms - sht_started_ >= 200U) {
    c.valid = false;
    sht_pending_ = false;
    return;
  }
  if (now_ms - sht_started_ < 12U) return;
  std::uint8_t b[6]{};
  // SHT4x data read has no register pointer after a measurement command.
  c.valid = bus_available() &&
      wire_->requestFrom(static_cast<std::uint8_t>(0x44),
                         static_cast<std::size_t>(6), true) == 6;
  c.valid = bus_available() && c.valid;
  for (int i = 0; i < 6 && c.valid; ++i) {
    if (wire_->available() < 1) c.valid = false;
    else { const int v = wire_->read(); if (v < 0) c.valid = false;
           else b[i] = static_cast<std::uint8_t>(v); }
  }
  sht41_accept_frame(c, b, now_ms, c.valid);
  sht_pending_ = false;
}
void AccessorySensors::barometer(std::uint32_t now_ms) {
  auto& b = data_.barometer;
  if (!b.present) return;
  // BMP280 is configured for ~1s normal-mode standby. Reading the bus
  // more often can return the SAME internal conversion with a new HTTP
  // timestamp. Keep accepted acquisition identity at least 1250ms apart.
  if (b.sample_seq != 0U && now_ms - b.at_ms < 1250U) return;
  // Two raw 20-bit ADC words from a single bounded burst. No reusing an
  // old pressure conversion if I2C fails or the NVM trim is implausible.
  std::uint8_t frame[6]{};
  if (!read(b.address, 0xF7, frame, 6)) { b.valid = false; return; }
  const auto press_adc = bmp280_raw20(frame);
  const auto temp_adc = bmp280_raw20(frame + 3);
  b.valid = bmp280_compensate(bmp_trim_, temp_adc, press_adc,
                              b.temp_centi, b.pressure_pa);
  if (b.valid) {
    b.at_ms = now_ms;
    b.sample_seq = next_nonzero_sensor_sequence(b.sample_seq);
  }
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
      if (g.fuel_valid) {
        g.fuel_sample_seq = next_nonzero_sensor_sequence(g.fuel_sample_seq);
        g.fuel_at_ms = now_ms;
      }
    }
  }
  if (g.monitor_present) {
    std::uint16_t status = 0, bus = 0, shunt = 0;
    unsigned bus_mv = 0;
    // TI INA226 SBOS547B: CVRF (Mask/Enable 0x06 bit 3) is
    // cleared on register read. Data registers remain readable between
    // conversions; require a new conversion before renewing provenance.
    const bool status_read = read16(0x40, 0x06, status);
    const bool reprime = monitor_reprime_;
    if (status_read) monitor_reprime_ = false;
    const bool ready = status_read && !reprime && (status & 0x0008U) != 0U;
    const bool overflow = ready && ina226_math_overflow(status);
    if (overflow) g.monitor_fault = Ina226Fault::MathOverflow;
    g.monitor_valid = ready && !overflow &&
                      read16(0x40, 0x02, bus) &&
                      ina226_bus_mv_from_raw(bus, bus_mv) &&
                      read16(0x40, 0x01, shunt);
    if (g.monitor_valid) {
      // Saturated signed raw ADC codes are not measurable current.
      // Do not refresh monitor validity or sequence for either rail.
      g.monitor_valid = ina226_shunt_uv_from_raw(shunt, g.shunt_uv);
      if (!g.monitor_valid) g.monitor_fault = Ina226Fault::ShuntSaturated;
    }
    if (g.monitor_valid) {
      g.monitor_fault = Ina226Fault::None;
      g.bus_mv = bus_mv;
      // Only after both actual registers were successfully acquired.
      g.monitor_sample_seq = next_nonzero_sensor_sequence(g.monitor_sample_seq);
      g.monitor_at_ms = now_ms;
#if DESK_ROBOT_PACK_SHUNT_MOHM == 5
      g.pack_current_valid = ina226_pack_current_ma(
          g.shunt_uv, DESK_ROBOT_PACK_SHUNT_MOHM, g.pack_current_ma);
#else
      g.pack_current_valid = false;  // known physical shunt absent
#endif
    } else {
      g.pack_current_valid = false;
    }
  }
  if (g.fuel_valid || g.monitor_valid) g.at_ms = now_ms;
  // Even valid integer milliamps do NOT certify pack charging, because
  // Kelvin tap routing, shunt tolerance and physical direction are unmeasured.
}
bool AccessorySensors::verify_mcp_ports() {
  return mcp_ports_.verify(
      [this](std::uint8_t reg, std::uint8_t& value) {
        return read(0x20, reg, &value, 1);
      },
      [this](std::uint8_t reg, std::uint8_t value) {
        return write8(0x20, reg, value);
      }, data_.optional_inputs.present);
}
void AccessorySensors::dock_status(std::uint32_t now_ms) {
  auto& dock = data_.dock;
  if (!dock.present) return;
  if (!verify_mcp_ports()) {
    invalidate_cached();
    return;
  }
  const bool had_contact = dock.left_seated || dock.right_seated ||
                           dock.input_good || dock.charge_indicated;
  const bool had_input = dock.input_good;
  std::uint8_t bits = 0;
  dock.valid = read(0x20, 0x12, &bits, 1);
  if (!dock.valid) return;
  dock.left_seated = (bits & 0x01U) != 0;
  dock.right_seated = (bits & 0x02U) != 0;
  dock.input_good = dock_pgood_asserted(bits);
  // CHG and PGOOD are independent open-drain physical status pins.
  // Do not mask a CHG-low/PGOOD-high contradiction; BodyControl must
  // see it and latch contact safety, while Mac reports a charger fault.
  dock.charge_indicated = dock_chg_asserted(bits);
  if (had_input != dock.input_good) {
    // Lane 4 may have been sampled immediately before this lane 5 edge.
    // Keep previous acquisition identities for replay detection, but revoke
    // their validity until independent power registers are read again.
    data_.gauge.fuel_valid = false;
    data_.gauge.monitor_valid = false;
    data_.gauge.pack_current_valid = false;
    // CVRF may have latched before the edge. Consume it without publishing
    // a sample on the next successful Mask/Enable read.
    monitor_reprime_ = true;
  }
  const bool has_contact = dock.left_seated || dock.right_seated ||
                           dock.input_good || dock.charge_indicated;
  // A contact transition invalidates any scan begun in the prior session.
  // Keep dock GPIO acquisition authoritative and restart only optional NFC.
  if (had_contact != has_contact) reset_nfc_protocol(now_ms);
  dock.at_ms = now_ms;
  dock.sample_seq = next_nonzero_sensor_sequence(dock.sample_seq); // fresh GPIOA read
}


#if DESK_ROBOT_ENABLE_HAPTIC
void AccessorySensors::haptic_step(std::uint32_t now_ms) {
  // Run only on the normal lane 5 pass AFTER fresh dock GPIOA acquisition.
  // No arbitrary I2C access while the critical 0x70 cliff mux is selected.
  if (!haptic_.ready() && !haptic_needs_low_) return;
  const auto& dock = data_.dock;
  const bool undocked = dock.present && dock.valid &&
      dock.sample_seq != 0U && now_ms - dock.at_ms < 250U &&
      !dock.left_seated && !dock.right_seated &&
      !dock.input_good && !dock.charge_indicated;
  const auto action = haptic_needs_low_
      ? HapticPulse::Action::TurnOff : haptic_.next(now_ms, undocked);
  if (action == HapticPulse::Action::None) return;
  const std::uint8_t expected =
      action == HapticPulse::Action::TurnOn ? 0x04U : 0x00U;
  std::uint8_t readback = 0xff;
  // Reuse the existing verified mux and register helper, with OLATB readback.
  const bool success = write8(0x20, 0x15, expected) &&
      read(0x20, 0x15, &readback, 1) && readback == expected;
  haptic_.completed(action, success, now_ms);
  if (success && expected == 0) haptic_needs_low_ = false;
  if (!success) {
    haptic_needs_low_ = true;
    invalidate_cached(); // do not preserve old dock evidence on bus failure
  }
}
#endif

void AccessorySensors::optional_gpio(std::uint32_t now_ms) {
  auto& extra = data_.optional_inputs;
  if (!extra.present) return;
  std::uint8_t bits = 0;
  extra.valid = read(0x20, 0x13, &bits, 1); // MCP23017 BANK=0 GPIOB
  if (!extra.valid) return;
  extra.reed_closed = (bits & 0x01U) == 0; // external 3.3V switch to GND
  extra.pir_active = (bits & 0x02U) != 0;  // verified 3.3V output
  // B3 is a separate read-only driver fault. MCP pullup B3 is disabled:
  // require a 3.3V far-end pullup on DRV8833 nFAULT and a weak pulldown
  // at the expander input, so an unplugged lead reads as a FAULT.
  extra.driver_fault_active = (bits & 0x08U) == 0;
  extra.at_ms = now_ms;
  extra.sample_seq = next_nonzero_sensor_sequence(extra.sample_seq);
}

bool AccessorySensors::nfc_write(
    std::uint8_t command, const std::uint8_t* body, std::size_t size) {
  std::uint8_t frame[32]{};
  const std::size_t n = pn532_encode(command, body, size, frame, sizeof(frame));
  if (!n || !bus_available()) return false;
  wire_->beginTransmission(kPn532Address);
  for (std::size_t i = 0; i < n; ++i) {
    if (wire_->write(frame[i]) != 1) {
      wire_->endTransmission(true); // always release an incomplete I2C write
      bus_available();
      return false;
    }
  }
  const bool acknowledged = wire_->endTransmission(true) == 0;
  return bus_available() && acknowledged;
}

int AccessorySensors::nfc_read(std::uint8_t* frame, std::uint8_t count) {
  // One bounded Wire transaction. Never use Seeed's blocking wait loops.
  if (!frame || count == 0 || count > kPn532MaxWire || !bus_available()) return -1;
  const auto received = wire_->requestFrom(kPn532Address, static_cast<std::size_t>(count), true);
  if (!bus_available() || received != count) return -1;
  for (std::uint8_t i = 0; i < count; ++i) {
    if (wire_->available() < 1) return -1;
    const int byte = wire_->read();
    if (byte < 0) return -1;
    frame[i] = static_cast<std::uint8_t>(byte);
  }
  if (frame[0] == 0) return 0; // chip busy: continue at a later mux slot
  return frame[0] == 1 ? 1 : -1;
}

void AccessorySensors::nfc_poll(std::uint32_t now_ms) {
  if (!nfc_collection_enabled_ || nfc_stage_ == NfcStage::Disabled) return;
  auto& tag = data_.nfc;
  const auto fail = [&]() {
    // Keep last confirmed identity for duplicate suppression on recovery.
    // Public AUX remains invalid until a complete checksum-valid scan.
    tag.transport_failed();
    nfc_stage_ = NfcStage::StartSam;
    nfc_last_scan_at_ms_ = now_ms; // bounded retry, no I2C flood
  };
  if (nfc_stage_ != NfcStage::Idle &&
      nfc_stage_ != NfcStage::StartSam &&
      nfc_stage_ != NfcStage::StartRetry &&
      now_ms - nfc_phase_at_ms_ > 1500U) {
    fail();
    return;
  }
  const std::uint8_t sam[] = {0x01, 0x14, 0x01};
  const std::uint8_t retries[] = {0x05, 0xff, 0x01, 0x01};
  const std::uint8_t scan[] = {0x01, 0x00};
  std::uint8_t frame[kPn532MaxWire]{};
  const std::uint8_t* payload = nullptr;
  std::size_t payload_len = 0;
  int ready = 0;
  switch (nfc_stage_) {
    case NfcStage::StartSam:
      if (now_ms - nfc_last_scan_at_ms_ < 500U) return;
      if (!nfc_write(0x14, sam, sizeof(sam))) { fail(); return; }
      nfc_stage_ = NfcStage::SamAck;
      nfc_phase_at_ms_ = now_ms;
      return;
    case NfcStage::SamAck:
    case NfcStage::RetryAck:
    case NfcStage::ScanAck:
      ready = nfc_read(frame, 7);
      if (ready == 0) return;
      if (ready != 1 || !pn532_ack(frame, 7)) { fail(); return; }
      nfc_stage_ = nfc_stage_ == NfcStage::SamAck ? NfcStage::SamResponse :
                   nfc_stage_ == NfcStage::RetryAck ? NfcStage::RetryResponse :
                                                      NfcStage::ScanResponse;
      return;
    case NfcStage::SamResponse:
    case NfcStage::RetryResponse: {
      const bool sam_response = nfc_stage_ == NfcStage::SamResponse;
      ready = nfc_read(frame, 10);
      if (ready == 0) return;
      if (ready != 1 ||
          !pn532_response(frame, 10, sam_response ? 0x14 : 0x32,
                          payload, payload_len) ||
          payload_len > 1 || (payload_len == 1 && payload[0] != 0)) {
        fail(); return;
      }
      nfc_stage_ = sam_response ? NfcStage::StartRetry : NfcStage::Idle;
      if (!sam_response) {
        tag.present = true; // verified chip response, not just I2C ACK
        nfc_last_scan_at_ms_ = now_ms;
      }
      return;
    }
    case NfcStage::StartRetry:
      // Seeed setPassiveActivationRetries(1) instead of infinite polling.
      if (!nfc_write(0x32, retries, sizeof(retries))) { fail(); return; }
      nfc_stage_ = NfcStage::RetryAck;
      nfc_phase_at_ms_ = now_ms;
      return;
    case NfcStage::Idle:
      if (now_ms - nfc_last_scan_at_ms_ < 350U) return;
      if (!nfc_write(0x4a, scan, sizeof(scan))) { fail(); return; }
      nfc_stage_ = NfcStage::ScanAck;
      nfc_phase_at_ms_ = now_ms;
      return;
    case NfcStage::ScanResponse: {
      ready = nfc_read(frame, static_cast<std::uint8_t>(kPn532MaxWire));
      if (ready == 0) return;
      if (ready != 1 ||
          !pn532_response(frame, kPn532MaxWire, 0x4a, payload, payload_len)) {
        fail(); return;
      }
      std::uint32_t token = 0;
      std::uint8_t uid_length = 0;
      const auto result = pn532_tag(payload, payload_len, token, uid_length);
      if (result == Pn532TagResult::Invalid) { fail(); return; }
      // Only completed, validated scans may change presentation identity.
      tag.completed_scan(result == Pn532TagResult::Present,
                         token, uid_length, now_ms);
      nfc_stage_ = NfcStage::Idle;
      nfc_last_scan_at_ms_ = now_ms;
      return;
    }
    case NfcStage::Disabled:
      return;
  }
}

bool AccessorySensors::poll(std::uint32_t now_ms,
                            Lane5SafetyCallback on_lane5_safety,
                            void* on_lane5_ctx) {
  if (!mux_present_ || (started_ && now_ms - last_ms_ < 12U)) return true;
  started_ = true;
  last_ms_ = now_ms;
  bus_blocked_ = false;
  const std::uint8_t lane = next_lane_;
  next_lane_ = lane >= 7 ? 1 : lane + 1;
  if (!select(lane)) {
    invalidate_cached();
    close();  // Best effort; TofBus independently verifies quiescence.
    return false;
  }
  switch (lane) {
    case 1: gesture_proximity(now_ms); break;
    case 2: force(now_ms); break;
    case 3: climate(now_ms); barometer(now_ms); break;
    case 4: power(now_ms); break;
    case 5:
      dock_status(now_ms);
      // Acquire mandatory GPB3 DRV8833 nFAULT alongside valid GPIOA before
      // any optional haptic or NFC I2C transactions can run.
      if (data_.dock.present && data_.dock.valid) {
        optional_gpio(now_ms);
      } else {
        data_.optional_inputs.valid = false;
        reset_nfc_protocol(now_ms); // no optional bus work or stale scan response on dock failure
      }
      // Publish dock/GPIOA/GPB3 safety state and coast motors before haptic/NFC.
      if (on_lane5_safety) on_lane5_safety(data_, now_ms, on_lane5_ctx);
      if (bus_available()) {
#if DESK_ROBOT_ENABLE_HAPTIC
        // Short, one-shot, touch-driven feedback only; dock monitor stays first.
        // Even a LOW retry needs a freshly verified register configuration.
        if (mcp_ports_.verified()) haptic_step(now_ms);
#endif
        if (data_.dock.present && data_.dock.valid && nfc_collection_enabled_) {
          if (nfc_pending_probe_) {
            nfc_pending_probe_ = false;
            if (probe(kPn532Address)) nfc_stage_ = NfcStage::StartSam;
          }
          nfc_poll(now_ms);
        }
      }
      break;
    case 6: angle(1, now_ms); break;
    case 7: angle(2, now_ms); break;
    default: break;
  }
  if (!close()) {
    // 0x70 ToF owner will also fail closed if this mux cannot quiesce.
    invalidate_cached();
    return false;
  }
  return true;
}
} // namespace desk_robot
#endif
