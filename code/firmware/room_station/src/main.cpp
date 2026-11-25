// One shared stationary USB room sensor, NOT a sixth robot or motor owner.
// Reuse pinned upstream Sensirion SCD4x, Adafruit BME68x/AMG88xx and
// ncmreynolds LD2410 Arduino drivers. Existing Adafruit Feather nRF52840.
// These are read-only environmental / proximity observations. No person
// identity, medical claims, motor command, battery or charger control.
// Hardware, serial electrical levels, I2C fit, gas warmup and thermal
// calibration still need a physical one-unit trial.
#include <Arduino.h>
#include <nrf.h>
#include <Wire.h>
#include <SensirionI2cScd4x.h>
#include <Adafruit_BME680.h>
#include <Adafruit_AMG88xx.h>
#include <ld2410.h>
#include <math.h>
#include <string.h>
#include "thermal_pixels.h"
#include "soil_sample.h"
#include "radar_sample_clock.h"
#include "radar_data_frame_gate.h"
#include "scd_sample_freshness.h"
#include "bme_completed_sample.h"
#include "usb_epoch_sync.h"
#include "sensor_recovery.h"

#ifndef ROOM_SOIL_FITTED
#define ROOM_SOIL_FITTED 0
#endif

namespace {
// nRF52840 WDT: run during sleep and debugger halt; timeout is
// (CRV + 1) / 32768 seconds. Feed only after the main loop returns
// from all synchronous bus operations. No timer/ISR can mask a hang.
class RoomLoopWatchdog {
 public:
  template <typename Registers>
  bool begin(Registers& regs) {
    if (!regs.RUNSTATUS) {
      regs.CONFIG = kRunDuringSleepAndHalt;
      regs.CRV = kReloadTicks;
      regs.RREN = 1U;
      regs.TASKS_START = 1U;
    }
    // A soft reset can preserve the watchdog. Do not overwrite locked
    // registers or feed another configuration's reload channels.
    ready_ = regs.CONFIG == kRunDuringSleepAndHalt &&
        regs.CRV == kReloadTicks && regs.RREN == 1U;
    return ready_;
  }
  template <typename Registers>
  void completed_pass(Registers& regs) const {
    if (ready_) regs.RR[0] = 0x6E524635U;
  }

 private:
  static constexpr uint32_t kRunDuringSleepAndHalt = 0x09U;
  static constexpr uint32_t kReloadTicks = 4U * 32768U - 1U;
  bool ready_ = false;
};
RoomLoopWatchdog room_watchdog;
bool room_watchdog_ready = false;

// Keep report formatting off the USB endpoint. The pinned TinyUSB CDC
// write() spins while DTR remains asserted and its TX FIFO is full.
constexpr size_t kMaxUsbLineBytes = 1536;
constexpr size_t kUsbWriteChunkBytes = 64;
class RoomUsbLine final : public Print {
 public:
  using Print::write;
  size_t write(uint8_t value) override {
    if (used_ == sizeof(bytes_)) {
      overflow_ = true;
      return 0;
    }
    bytes_[used_++] = value;
    return 1;
  }
  void reset() { used_ = 0; overflow_ = false; }
  bool valid() const {
    return !overflow_ && used_ != 0 && bytes_[used_ - 1] == '\n';
  }
  size_t size() const { return used_; }
  const uint8_t* data() const { return bytes_; }

 private:
  uint8_t bytes_[kMaxUsbLineBytes] = {};
  size_t used_ = 0;
  bool overflow_ = false;
};

// One in-flight line and the latest waiting SYNC ACK. A new challenge
// retires any line that has not started; a partially sent line finishes
// first. The leading ACK newline isolates any interrupted USB line, and
// the host discards everything before its matching nonce.
class RoomUsbTx {
 public:
  void queue_ack(const char* token) {
    memcpy(ack_, "\nSYNC_ACK ", 10);
    memcpy(ack_ + 10, token, 16);
    ack_[26] = '\r';
    ack_[27] = '\n';
    ack_pending_ = true;
    if (sent_ == 0) pending_size_ = 0;
  }
  bool queue_report(const RoomUsbLine& line) {
    if (pending_size_ || ack_pending_ || !line.valid()) return false;
    memcpy(pending_, line.data(), line.size());
    pending_size_ = line.size();
    return true;
  }
  template <typename Port>
  void step(Port& port) {
    if (!port) {
      pending_size_ = sent_ = 0;
      ack_pending_ = false;
      return;
    }
    if (!pending_size_) {
      if (!ack_pending_) return;
      memcpy(pending_, ack_, sizeof(ack_));
      pending_size_ = sizeof(ack_);
      ack_pending_ = false;
    }
    const int capacity = port.availableForWrite();
    if (capacity <= 0) return;
    size_t count = pending_size_ - sent_;
    if (count > static_cast<size_t>(capacity))
      count = static_cast<size_t>(capacity);
    if (count > kUsbWriteChunkBytes) count = kUsbWriteChunkBytes;
    // This is the station's sole CDC writer. Never request more than the
    // current FIFO space, and keep any short-write suffix for a later loop.
    const size_t written = port.write(pending_ + sent_, count);
    sent_ += written;
    if (written) port.flush();
    if (sent_ == pending_size_) pending_size_ = sent_ = 0;
  }

 private:
  uint8_t pending_[kMaxUsbLineBytes] = {};
  size_t pending_size_ = 0;
  size_t sent_ = 0;
  uint8_t ack_[28] = {};
  bool ack_pending_ = false;
};
RoomUsbLine telemetry;
RoomUsbTx usb_tx;

constexpr uint32_t kReportMs = 1000;
constexpr uint32_t kScdStaleMs = 8500;
constexpr uint32_t kBmeStaleMs = 3000;
constexpr uint32_t kRadarStaleMs = 3000;
constexpr uint32_t kThermalStaleMs = 3000;
constexpr uint32_t kThermalScanMaxMs = 250;
constexpr uint32_t kScdNoSampleMs = 15000;
constexpr uint8_t kBmePrimary = 0x77;
constexpr uint8_t kBmeAlternate = 0x76;
constexpr uint8_t kAmgAddress = 0x69;
// Common 3.3V I2C bus: SCD40 = 0x62, BME688 = 0x77/0x76, AMG8833 = 0x69.
// LD2410C uses a separate 256000baud 3.3V UART on Serial1; its power rail
// and TX/RX exact voltage/pin orientation require the carrier schematic.
SensirionI2cScd4x scd;
Adafruit_BME680 bme(&Wire);
// Adapt the pinned AMG88xx initialization to checked, staged I2C writes.
// Panasonic Grid-EYE I2C interface (I2C_interface.pdf), power/reset sequence:
// after sleep -> normal wait 50 ms; initial reset -> flag reset wait 2 ms;
// wait more than two frame periods before using pixels. Explicitly establish
// sleep before waking because a previous failed recovery may leave any mode.
class AmgRecovery {
 public:
  void begin() { phase_ = Phase::normalize; ready_ = false; }
  bool active() const { return phase_ != Phase::idle; }
  bool take_ready() {
    const bool ready = ready_;
    ready_ = false;
    return ready;
  }
  template <typename WireLike>
  bool step(WireLike& wire, uint32_t now) {
    if (phase_ == Phase::idle) return false;
    const uint32_t elapsed = now - phase_ms_;
    if (phase_ == Phase::settle) {
      if (elapsed >= 250U) {
        phase_ = Phase::idle;
        ready_ = true;
      }
      return false;
    }
    if ((phase_ == Phase::sleep || phase_ == Phase::initial_reset) &&
        elapsed < 50U) return false;
    if ((phase_ == Phase::wake || phase_ == Phase::flag_reset) &&
        elapsed < 2U) return false;
    uint8_t reg = 0, value = 0;
    Phase next = Phase::idle;
    switch (phase_) {
      case Phase::normalize:
        reg = AMG88xx_PCTL; value = AMG88xx_NORMAL_MODE;
        next = Phase::sleep; break;
      case Phase::sleep:
        reg = AMG88xx_PCTL; value = 0x10; // Panasonic sleep mode
        next = Phase::wake; break;
      case Phase::wake:
        reg = AMG88xx_PCTL; value = AMG88xx_NORMAL_MODE;
        next = Phase::initial_reset; break;
      case Phase::initial_reset:
        reg = AMG88xx_RST; value = AMG88xx_INITIAL_RESET;
        next = Phase::flag_reset; break;
      case Phase::flag_reset:
        reg = AMG88xx_RST; value = AMG88xx_FLAG_RESET;
        next = Phase::interrupt; break;
      case Phase::interrupt:
        reg = AMG88xx_INTC; value = 0;
        next = Phase::rate; break;
      case Phase::rate:
        reg = AMG88xx_FPSC; value = AMG88xx_FPS_10;
        next = Phase::settle; break;
      default: return false;
    }
    wire.beginTransmission(kAmgAddress);
    const bool reg_ok = wire.write(reg) == 1;
    const bool value_ok = wire.write(value) == 1;
    const int result = wire.endTransmission();
    phase_ = reg_ok && value_ok && result == 0 ? next : Phase::idle;
    phase_ms_ = millis();
    return true;
  }

 private:
  enum class Phase : uint8_t {
    idle, normalize, sleep, wake, initial_reset, flag_reset, interrupt, rate, settle
  };
  Phase phase_ = Phase::idle;
  uint32_t phase_ms_ = 0;
  bool ready_ = false;
};
AmgRecovery amg_recovery;
// Pass every radar byte to the pinned decoder unchanged while independently
// recognizing complete validated data frames. A stray UART byte or command
// ACK must not refresh the timestamp of cached target data.
class RadarObservedUart final : public Stream {
 public:
  explicit RadarObservedUart(Stream& source) : source_(source) {}
  void begin_poll() { remaining_ = kReadBudget; }
  int available() override {
    if (remaining_ == 0) return 0;
    const int count = source_.available();
    if (count <= 0) return 0;
    return count < remaining_ ? count : remaining_;
  }
  int peek() override { return remaining_ ? source_.peek() : -1; }
  int read() override {
    if (remaining_ == 0) return -1;
    --remaining_;
    const int value = source_.read();
    if (value < 0) {
      remaining_ = 0;
      return value;
    }
    if (gate_.consume(static_cast<uint8_t>(value)))
      data_frame_complete_ = true;
    return value;
  }
  void flush() override { source_.flush(); }
  size_t write(uint8_t value) override { return source_.write(value); }
  using Print::write;
  const desk_robot_room::RadarTargetSample& completed_sample() const {
    return gate_.completed_sample();
  }
  bool take_completed_data_frame() {
    const bool complete = data_frame_complete_;
    data_frame_complete_ = false;
    return complete;
  }

 private:
  // The pinned decoder drains until available() is zero. Bound one pass
  // below its 256-byte ring size; frame parser state survives across polls.
  static constexpr int kReadBudget = 128;
  int remaining_ = 0;
  Stream& source_;
  desk_robot_room::RadarDataFrameGate gate_;
  bool data_frame_complete_ = false;
};
RadarObservedUart radar_uart(Serial1);
ld2410 radar;
desk_robot_room::RadarSampleClock radar_sample_clock;
desk_robot_room::RadarTargetSample radar_completed;
desk_robot_room::UsbEpochSync usb_epoch_sync;
desk_robot_room::SensorRecoverySchedule sensor_recovery;
bool scd_started = false;
bool scd_stop_pending = false;
bool scd_valid = false;
uint32_t scd_stop_ms = 0;
uint32_t scd_started_ms = 0;
bool bme_started = false;
bool bme_pending = false;
uint32_t bme_last_start_ms = 0;
desk_robot_room::BmeCompletedSample bme_completed;
bool amg_started = false;
uint16_t co2_ppm = 0;
float scd_temp = 0, scd_humidity = 0;
uint32_t last_scd_ms = 0;
uint32_t last_report_ms = 0;
uint32_t sequence = 0;
float thermal[AMG88xx_PIXEL_ARRAY_SIZE] = {};
float thermal_staging[AMG88xx_PIXEL_ARRAY_SIZE] = {};
bool thermal_valid = false, thermal_scan_active = false;
bool thermal_ever_requested = false;
uint8_t thermal_next_chunk = 0;
uint32_t thermal_requested_ms = 0, thermal_started_ms = 0;
uint32_t thermal_sample_ms = 0;

bool finite_temperature(float temp) {
  return isfinite(temp) && temp >= -40.0f && temp <= 125.0f;
}
void jsbool(bool value) { telemetry.print(value ? F("true") : F("false")); }
void number(float value, int decimals = 2) {
  // Only call after validating isfinite. Never emit NaN/Infinity JSON tokens.
  telemetry.print(value, decimals);
}
void scd_step(uint32_t now) {
  if (scd_started) {
    bool ready = false;
    const int readiness_status = scd.getDataReadyStatus(ready);
    bool measurement_valid = false;
    if (readiness_status == 0 && ready) {
      uint16_t ppm = 0;
      float t = 0, rh = 0;
      measurement_valid = scd.readMeasurement(ppm, t, rh) == 0 &&
          ppm > 0 && ppm <= 50000 && finite_temperature(t) &&
          isfinite(rh) && rh >= 0 && rh <= 100;
      if (measurement_valid) {
        co2_ppm = ppm;
        scd_temp = t;
        scd_humidity = rh;
        last_scd_ms = millis();
      }
    }
    now = millis();
    // A read/transport failure or missing conversions after a sensor reset
    // retires this SCD generation. Do not publish cached pre-reset CO2.
    scd_valid = desk_robot_room::scd_sample_valid_after_poll(
        scd_valid, readiness_status, ready, measurement_valid);
    if (readiness_status != 0 || (ready && !measurement_valid) ||
        (now - scd_started_ms >= kScdNoSampleMs &&
         (!scd_valid || now - last_scd_ms >= kScdNoSampleMs))) {
      scd_started = false;
      scd_valid = false;
    }
  }
}
void scd_observation(uint32_t now) {
  const bool fresh = scd_started && scd_valid && now - last_scd_ms <= kScdStaleMs;
  telemetry.print(F("\"scd40\":{\"valid\":")); jsbool(fresh);
  if (fresh) {
    telemetry.print(F(",\"sample_ms\":")); telemetry.print(last_scd_ms);
    telemetry.print(F(",\"co2_ppm\":")); telemetry.print(co2_ppm);
    telemetry.print(F(",\"temp_c\":")); number(scd_temp);
    telemetry.print(F(",\"humidity_pct\":")); number(scd_humidity);
  }
  telemetry.print('}');
}
// Pinned Adafruit BME680 v2.0.5: beginReading starts a forced conversion;
// remainingReadingMillis is nonblocking, and endReading must run only at
// reading_complete. The LD2410C UART must remain serviced while the
// BME688 gas heater and oversampling complete.
void bme_step(uint32_t now) {
  if (!bme_started) return;
  if (!bme_pending) {
    if (bme_last_start_ms != 0 && now - bme_last_start_ms < kReportMs)
      return;
    bme_last_start_ms = now;
    // Pinned Adafruit_BME680 2.0.5 endReading() returns true even when
    // n_fields == 0; in that case its public values remain unchanged.
    // Clear the source's zero-gas sentinel before EVERY acquisition so
    // empty conversions cannot refresh a previous valid gas sample.
    bme.gas_resistance = 0;
    bme_pending = bme.beginReading() != 0U;
    if (!bme_pending) {
      bme_completed.invalidate();
      bme_started = false;
    }
    return;
  }
  const int remaining = bme.remainingReadingMillis();
  if (remaining > Adafruit_BME680::reading_complete) return;
  bme_pending = false;
  if (remaining != Adafruit_BME680::reading_complete || !bme.endReading()) {
    bme_completed.invalidate();
    bme_started = false;
    return;
  }
  const bool complete = finite_temperature(bme.temperature)
      && isfinite(bme.humidity) && bme.humidity >= 0 && bme.humidity <= 100
      // Match the Mac room decoder. An out-of-range BME must not
      // poison the entire USB frame and hide independent room sensors.
      && isfinite(bme.pressure) && bme.pressure >= 30000.0f
      && bme.pressure <= 125000.0f
      && isfinite(bme.gas_resistance) && bme.gas_resistance >= 1
      && bme.gas_resistance <= 1000000000U;
  if (complete) {
    // Publish every field together with the actual completed-conversion time.
    // Upstream scratch may be reset while the next conversion is pending.
    bme_completed.publish(bme.temperature, bme.humidity, bme.pressure,
                          bme.gas_resistance, millis());
  } else {
    bme_completed.invalidate();
    bme_started = false;
  }
}
void bme_observation(uint32_t now) {
  // Serial reporting never starts or waits for a gas conversion.
  // Preserve the actual last completed sample time, not the report time.
  const bool fresh = bme_completed.fresh(now, kBmeStaleMs);
  telemetry.print(F("\"bme688\":{\"valid\":")); jsbool(fresh);
  if (fresh) {
    telemetry.print(F(",\"sample_ms\":")); telemetry.print(bme_completed.sample_ms);
    telemetry.print(F(",\"temp_c\":")); number(bme_completed.temperature_c);
    telemetry.print(F(",\"humidity_pct\":")); number(bme_completed.humidity_pct);
    telemetry.print(F(",\"pressure_pa\":")); number(bme_completed.pressure_pa, 0);
    telemetry.print(F(",\"gas_ohms\":")); telemetry.print(bme_completed.gas_ohms);
    // Gas resistance is raw resistance, never calibrated VOC or AQI.
  }
  telemetry.print('}');
}
void radar_observation(uint32_t now) {
  // The pinned v0.2.2 driver's read_frame_ can leave queued frames, and
  // isConnected() can parse another frame. Never mix those live getters
  // with the raw packet receipt clock. Expire the completed tuple locally.
  // A static/moving echo is not authentication or a particular human.
  const bool connected = radar_sample_clock.fresh(now, kRadarStaleMs);
  telemetry.print(F("\"ld2410c\":{\"valid\":")); jsbool(connected);
  if (connected) {
    telemetry.print(F(",\"sample_ms\":"));
    telemetry.print(radar_sample_clock.sample_ms());
    telemetry.print(F(",\"presence\":")); jsbool(radar_completed.presence);
    telemetry.print(F(",\"stationary\":")); jsbool(radar_completed.stationary);
    telemetry.print(F(",\"moving\":")); jsbool(radar_completed.moving);
    telemetry.print(F(",\"stationary_cm\":"));
    telemetry.print(radar_completed.stationary_cm);
    telemetry.print(F(",\"moving_cm\":")); telemetry.print(radar_completed.moving_cm);
  }
  telemetry.print('}');
}
#if ROOM_SOIL_FITTED
desk_robot_room::SoilSample soil_sample;
uint32_t soil_sample_ms = 0;
#endif
void soil_step() {
#if ROOM_SOIL_FITTED
  // Three actual ADC acquisitions; no moisture calibration is inferred.
  soil_sample = desk_robot_room::read_soil_sample(
      []() { return analogRead(A0); });
  soil_sample_ms = millis();
#endif
}
void soil_observation(uint32_t now) {
  telemetry.print(F("\"soil\":{\"valid\":"));
#if ROOM_SOIL_FITTED
  const bool fresh = soil_sample.valid && now - soil_sample_ms <= kReportMs;
  jsbool(fresh);
  if (fresh) {
    telemetry.print(F(",\"sample_ms\":")); telemetry.print(soil_sample_ms);
    telemetry.print(F(",\"raw_adc\":")); telemetry.print(soil_sample.raw_adc);
  }
#else
  (void)now;
  jsbool(false);
#endif
  telemetry.print('}');
}
// The pinned Adafruit AMG88xx readPixels() returns void and its underlying
// I2C read discards transfer failure. Reject a partial/failed pixel frame.
// Retain Adafruit's register definitions and its contiguous pixel
// register layout and the portable tested eight 16-byte read helper.
// This stationary sensor never authorizes motor or charging commands.
// Read only one 16-byte I2C chunk per loop iteration. The LD2410C
// 256000-baud UART needs service between transfers; do not block it
// through eight sensor transactions inside one JSON report.
void thermal_step(uint32_t now) {
  if (!amg_started) return;
  if (!thermal_scan_active) {
    if (thermal_ever_requested && now - thermal_requested_ms < kReportMs)
      return;
    thermal_ever_requested = true;
    thermal_requested_ms = thermal_started_ms = now;
    thermal_next_chunk = 0;
    thermal_scan_active = true;
  }
  // A stalled or partially missing scan is not a completed frame.
  // These are sequential pixel readings, not a simultaneous thermal image.
  const bool chunk_ok = now - thermal_started_ms < kThermalScanMaxMs &&
      desk_robot_room::read_thermal_chunk(
          Wire, kAmgAddress, thermal_next_chunk,
          thermal_staging + 8U * thermal_next_chunk);
  now = millis();
  if (!chunk_ok || now - thermal_started_ms >= kThermalScanMaxMs) {
    thermal_scan_active = false;
    thermal_valid = false;
    amg_started = false;
    return;
  }
  if (++thermal_next_chunk == AMG88xx_PIXEL_ARRAY_SIZE / 8U) {
    for (unsigned i = 0; i < AMG88xx_PIXEL_ARRAY_SIZE; ++i)
      thermal[i] = thermal_staging[i];
    thermal_sample_ms = now;
    thermal_valid = true;
    thermal_scan_active = false;
  }
}
void thermal_observation(uint32_t now) {
  // Never read I2C in the report path or stamp cached pixels with now.
  const bool valid = thermal_valid && now - thermal_sample_ms <= kThermalStaleMs;
  telemetry.print(F("\"amg8833\":{\"valid\":")); jsbool(valid);
  if (valid) {
    telemetry.print(F(",\"sample_ms\":")); telemetry.print(thermal_sample_ms);
    telemetry.print(F(",\"pixels_c\":["));
    for (unsigned i = 0; i < AMG88xx_PIXEL_ARRAY_SIZE; ++i) {
      if (i) telemetry.print(',');
      number(thermal[i], 2);
    }
    telemetry.print(']');
  }
  telemetry.print('}');
}
// Retry only one missing I2C peripheral in each main-loop pass. Each
// attempt is spaced by the same monotonic millis() gate, including rollover.
// Wait phases are split across passes. The pinned Wire core still has
// synchronous hardware event waits without an I2C transaction timeout.
bool begin_bme() {
  if (!bme.begin(kBmePrimary) && !bme.begin(kBmeAlternate))
    return false;
  bme.setTemperatureOversampling(BME680_OS_8X);
  bme.setHumidityOversampling(BME680_OS_2X);
  bme.setPressureOversampling(BME680_OS_4X);
  bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
  bme.setGasHeater(320, 150);
  bme_pending = false;
  bme_last_start_ms = 0;
  bme_completed.invalidate();
  return true;
}
void recover_sensors(uint32_t now) {
  // Sensirion requires 500 ms after stopPeriodicMeasurement before start.
  // Split the two I2C commands across loop passes instead of delay(500).
  if (scd_stop_pending && desk_robot_room::scd_stop_settled(now, scd_stop_ms)) {
    scd_stop_pending = false;
    scd_started = scd.startPeriodicMeasurement() == 0;
    scd_started_ms = millis();
    return;
  }
  const bool amg_transaction = amg_recovery.step(Wire, now);
  if (amg_recovery.take_ready()) amg_started = true;
  if (amg_transaction) return;
  const bool active[] = {scd_started || scd_stop_pending,
                         bme_started, amg_started || amg_recovery.active()};
  const int sensor = sensor_recovery.next(now, active);
  if (sensor == desk_robot_room::SensorRecoverySchedule::kScd) {
    scd_valid = false;
    last_scd_ms = 0;
    scd.begin(Wire, SCD41_I2C_ADDR_62);
    // The pinned Sensirion stopPeriodicMeasurement() internally delay(500).
    // Send that same documented command as one I2C transaction;
    // start only after 500 ms in a different main-loop pass.
    Wire.beginTransmission(SCD41_I2C_ADDR_62);
    Wire.write(0x3f);
    Wire.write(0x86);
    if (Wire.endTransmission() == 0) {
      // The required settle interval starts after the successful transfer.
      scd_stop_ms = millis();
      scd_stop_pending = true;
    }
  } else if (sensor == desk_robot_room::SensorRecoverySchedule::kBme) {
    bme_started = begin_bme();
    if (!bme_started) bme_completed.invalidate();
  } else if (sensor == desk_robot_room::SensorRecoverySchedule::kAmg) {
    thermal_scan_active = false;
    thermal_valid = false;
    amg_started = false;
    amg_recovery.begin();
    thermal_ever_requested = false;
  }
}
void report(uint32_t now) {
  // One bounded, newline-delimited source-of-observation frame each second.
  // Mac owns reconnect epochs, replay rejection, user consent and five pet
  // interpretation. The board does NOT speak, move, recognize or charge.
  // Formatting uses only already completed sensor acquisitions.
  telemetry.reset();
  telemetry.print(F("{\"v\":1,\"station\":\"room-pod-01\",\"seq\":"));
  telemetry.print(++sequence);
  telemetry.print(F(",\"at_ms\":")); telemetry.print(now);
  telemetry.print(F(",\"readings\":{"));
  scd_observation(now); telemetry.print(',');
  bme_observation(now); telemetry.print(',');
  radar_observation(now); telemetry.print(',');
  soil_observation(now); telemetry.print(',');
  thermal_observation(now);
  telemetry.println(F("}}"));
  // No queue growth or sensor-loop wait when the laptop is not reading.
  usb_tx.queue_report(telemetry);
}
}  // namespace

void setup() {
  room_watchdog_ready = room_watchdog.begin(*NRF_WDT);
  if (!room_watchdog_ready) return;
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(100000);
  // Probes now run through recover_sensors() so a missing module at boot
  // is retried without deliberately sleeping through radar/USB service.
  Serial1.begin(256000);  // LD2410C, different UART from USB CDC Serial
  // Pinned ld2410 v0.2.2 otherwise blocks probing the optional radar
  // firmware for up to one second when the board is missing. Keep the
  // shared climate and thermal station independently bootable.
  radar.begin(radar_uart, false);
#if ROOM_SOIL_FITTED
  analogReadResolution(12);
#endif
}
void loop() {
  if (!room_watchdog_ready) return;
  // Bounded read-only causal handshake, never a command to actuate.
  // Queue the response ahead of any subsequently generated JSON report.
  // Read at most 32 bytes each pass so live radar UART remains serviced.
  for (uint8_t count = 0; count < 32 && Serial.available() > 0; ++count) {
    const int value = Serial.read();
    if (value < 0) break;
    if (usb_epoch_sync.consume(static_cast<uint8_t>(value))) {
      usb_tx.queue_ack(usb_epoch_sync.token());
    }
  }
  radar_uart.begin_poll();
  radar.read();
  uint32_t now = millis();
  // ld2410::read() returns true on any byte, even an incomplete frame.
  // Only a complete protocol-validated *data* packet can renew acquisition.
  if (radar_uart.take_completed_data_frame()) {
    radar_completed = radar_uart.completed_sample();
    radar_sample_clock.observe(true, true, now);
  }
  recover_sensors(now);
  now = millis();
  bme_step(now); // no heater-time sleep; preserve 256000 baud radar service
  now = millis();
  thermal_step(now); // one I2C chunk per loop, complete frame only
  // A completed scan can advance sample_ms during the transfer. Refresh
  // the report clock so its timestamp never predates that acquisition.
  now = millis();
  if (now - last_report_ms >= kReportMs) {
    last_report_ms = now;
    // Acquire periodic sensors even when an older USB line is in flight.
    scd_step(now);
    soil_step();
    now = millis();
    report(now);
  }
  usb_tx.step(Serial); // one FIFO-space-limited chunk; never wait for a reader
  room_watchdog.completed_pass(*NRF_WDT);
}
