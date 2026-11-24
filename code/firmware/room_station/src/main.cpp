// One shared stationary USB room sensor, NOT a sixth robot or motor owner.
// Reuse pinned upstream Sensirion SCD4x, Adafruit BME68x/AMG88xx and
// ncmreynolds LD2410 Arduino drivers. Existing Adafruit Feather nRF52840.
// These are read-only environmental / proximity observations. No person
// identity, medical claims, motor command, battery or charger control.
// Hardware, serial electrical levels, I2C fit, gas warmup and thermal
// calibration still need a physical one-unit trial.
#include <Arduino.h>
#include <Wire.h>
#include <SensirionI2cScd4x.h>
#include <Adafruit_BME680.h>
#include <Adafruit_AMG88xx.h>
#include <ld2410.h>
#include <math.h>
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
constexpr uint32_t kReportMs = 1000;
constexpr uint32_t kScdStaleMs = 8500;
constexpr uint32_t kBmeStaleMs = 3000;
constexpr uint32_t kRadarStaleMs = 3000;
constexpr uint32_t kThermalStaleMs = 3000;
constexpr uint32_t kThermalScanMaxMs = 250;
constexpr uint32_t kBootWaitMs = 1200;
constexpr uint32_t kScdNoSampleMs = 15000;
constexpr uint8_t kBmePrimary = 0x77;
constexpr uint8_t kBmeAlternate = 0x76;
constexpr uint8_t kAmgAddress = 0x69;
// Common 3.3V I2C bus: SCD40 = 0x62, BME688 = 0x77/0x76, AMG8833 = 0x69.
// LD2410C uses a separate 256000baud 3.3V UART on Serial1; its power rail
// and TX/RX exact voltage/pin orientation require the carrier schematic.
SensirionI2cScd4x scd;
Adafruit_BME680 bme(&Wire);
Adafruit_AMG88xx amg;
// Pass every radar byte to the pinned decoder unchanged while independently
// recognizing complete validated data frames. A stray UART byte or command
// ACK must not refresh the timestamp of cached target data.
class RadarObservedUart final : public Stream {
 public:
  explicit RadarObservedUart(Stream& source) : source_(source) {}
  int available() override { return source_.available(); }
  int peek() override { return source_.peek(); }
  int read() override {
    const int value = source_.read();
    if (value >= 0 && gate_.consume(static_cast<uint8_t>(value)))
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
void jsbool(bool value) { Serial.print(value ? F("true") : F("false")); }
void number(float value, int decimals = 2) {
  // Only call after validating isfinite. Never emit NaN/Infinity JSON tokens.
  Serial.print(value, decimals);
}
void scd_observation(uint32_t now) {
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
        last_scd_ms = now;
      }
    }
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
  const bool fresh = scd_started && scd_valid && now - last_scd_ms <= kScdStaleMs;
  Serial.print(F("\"scd40\":{\"valid\":")); jsbool(fresh);
  if (fresh) {
    Serial.print(F(",\"sample_ms\":")); Serial.print(last_scd_ms);
    Serial.print(F(",\"co2_ppm\":")); Serial.print(co2_ppm);
    Serial.print(F(",\"temp_c\":")); number(scd_temp);
    Serial.print(F(",\"humidity_pct\":")); number(scd_humidity);
  }
  Serial.print('}');
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
                          bme.gas_resistance, now);
  } else {
    bme_completed.invalidate();
    bme_started = false;
  }
}
void bme_observation(uint32_t now) {
  // Serial reporting never starts or waits for a gas conversion.
  // Preserve the actual last completed sample time, not the report time.
  const bool fresh = bme_completed.fresh(now, kBmeStaleMs);
  Serial.print(F("\"bme688\":{\"valid\":")); jsbool(fresh);
  if (fresh) {
    Serial.print(F(",\"sample_ms\":")); Serial.print(bme_completed.sample_ms);
    Serial.print(F(",\"temp_c\":")); number(bme_completed.temperature_c);
    Serial.print(F(",\"humidity_pct\":")); number(bme_completed.humidity_pct);
    Serial.print(F(",\"pressure_pa\":")); number(bme_completed.pressure_pa, 0);
    Serial.print(F(",\"gas_ohms\":")); Serial.print(bme_completed.gas_ohms);
    // Gas resistance is raw resistance, never calibrated VOC or AQI.
  }
  Serial.print('}');
}
void radar_observation(uint32_t now) {
  // The pinned v0.2.2 driver's read_frame_ can leave queued frames, and
  // isConnected() can parse another frame. Never mix those live getters
  // with the raw packet receipt clock. Expire the completed tuple locally.
  // A static/moving echo is not authentication or a particular human.
  const bool connected = radar_sample_clock.fresh(now, kRadarStaleMs);
  Serial.print(F("\"ld2410c\":{\"valid\":")); jsbool(connected);
  if (connected) {
    Serial.print(F(",\"sample_ms\":"));
    Serial.print(radar_sample_clock.sample_ms());
    Serial.print(F(",\"presence\":")); jsbool(radar_completed.presence);
    Serial.print(F(",\"stationary\":")); jsbool(radar_completed.stationary);
    Serial.print(F(",\"moving\":")); jsbool(radar_completed.moving);
    Serial.print(F(",\"stationary_cm\":"));
    Serial.print(radar_completed.stationary_cm);
    Serial.print(F(",\"moving_cm\":")); Serial.print(radar_completed.moving_cm);
  }
  Serial.print('}');
}
void soil_observation(uint32_t now) {
  Serial.print(F("\"soil\":{\"valid\":"));
#if ROOM_SOIL_FITTED
  // Each report uses three actual bounded Arduino ADC acquisitions. Rail,
  // saturation and gross noise faults must never appear as fresh plant
  // evidence. This remains raw ADC, not moisture % or proof of a live probe.
  const auto sample = desk_robot_room::read_soil_sample(
      []() { return analogRead(A0); });
  jsbool(sample.valid);
  if (sample.valid) {
    Serial.print(F(",\"sample_ms\":")); Serial.print(now);
    Serial.print(F(",\"raw_adc\":")); Serial.print(sample.raw_adc);
  }
#else
  (void)now;
  jsbool(false);
#endif
  Serial.print('}');
}
// The pinned Adafruit AMG88xx readPixels() returns void and its underlying
// I2C read discards transfer failure. Reject a partial/failed pixel frame.
// Retain Adafruit's normal device initialization and its contiguous pixel
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
  Serial.print(F("\"amg8833\":{\"valid\":")); jsbool(valid);
  if (valid) {
    Serial.print(F(",\"sample_ms\":")); Serial.print(thermal_sample_ms);
    Serial.print(F(",\"pixels_c\":["));
    for (unsigned i = 0; i < AMG88xx_PIXEL_ARRAY_SIZE; ++i) {
      if (i) Serial.print(',');
      number(thermal[i], 2);
    }
    Serial.print(']');
  }
  Serial.print('}');
}
// Retry only one missing I2C peripheral in each main-loop pass. Each
// attempt is spaced by the same monotonic millis() gate, including rollover.
// A healthy radar, USB handshake, or unrelated sensor never waits on recovery.
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
  const bool active[] = {scd_started || scd_stop_pending,
                         bme_started, amg_started};
  const int sensor = sensor_recovery.next(now, active);
  if (sensor == desk_robot_room::SensorRecoverySchedule::kScd) {
    scd_valid = false;
    last_scd_ms = 0;
    scd.begin(Wire, SCD41_I2C_ADDR_62);
    // The pinned Sensirion stopPeriodicMeasurement() internally delay(500).
    // Send that same documented command as one bounded I2C transaction;
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
    amg_started = amg.begin(kAmgAddress);
    thermal_ever_requested = false;
  }
}
void report(uint32_t now) {
  // One bounded, newline-delimited source-of-observation frame each second.
  // Mac owns reconnect epochs, replay rejection, user consent and five pet
  // interpretation. The board does NOT speak, move, recognize or charge.
  Serial.print(F("{\"v\":1,\"station\":\"room-pod-01\",\"seq\":"));
  Serial.print(++sequence);
  Serial.print(F(",\"at_ms\":")); Serial.print(now);
  Serial.print(F(",\"readings\":{"));
  scd_observation(now); Serial.print(',');
  bme_observation(now); Serial.print(',');
  radar_observation(now); Serial.print(',');
  soil_observation(now); Serial.print(',');
  thermal_observation(now);
  Serial.println(F("}}"));
}
}  // namespace

void setup() {
  Serial.begin(115200);
  const uint32_t start = millis();
  while (!Serial && millis() - start < kBootWaitMs) delay(5);
  Wire.begin();
  Wire.setClock(100000);
  // Probes now run through recover_sensors() so a missing module at boot
  // is retried without rebooting the Feather or blocking radar/USB service.
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
  // Bounded read-only causal handshake, never a command to actuate.
  // The response is written before any subsequently generated JSON report.
  // Read at most 32 bytes each pass so live radar UART remains serviced.
  for (uint8_t count = 0; count < 32 && Serial.available() > 0; ++count) {
    const int value = Serial.read();
    if (value < 0) break;
    if (usb_epoch_sync.consume(static_cast<uint8_t>(value))) {
      Serial.print(F("SYNC_ACK "));
      Serial.println(usb_epoch_sync.token());
    }
  }
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
    report(now);
  }
}
