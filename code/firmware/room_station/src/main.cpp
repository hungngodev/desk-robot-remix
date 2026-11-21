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
#include "scd_sample_freshness.h"
#include "bme_completed_sample.h"
#include "usb_epoch_sync.h"

#ifndef ROOM_SOIL_FITTED
#define ROOM_SOIL_FITTED 0
#endif

namespace {
constexpr uint32_t kReportMs = 1000;
constexpr uint32_t kScdStaleMs = 8500;
constexpr uint32_t kBmeStaleMs = 3000;
constexpr uint32_t kThermalStaleMs = 3000;
constexpr uint32_t kThermalScanMaxMs = 250;
constexpr uint32_t kBootWaitMs = 1200;
constexpr uint8_t kBmePrimary = 0x77;
constexpr uint8_t kBmeAlternate = 0x76;
constexpr uint8_t kAmgAddress = 0x69;
// Common 3.3V I2C bus: SCD40 = 0x62, BME688 = 0x77/0x76, AMG8833 = 0x69.
// LD2410C uses a separate 256000baud 3.3V UART on Serial1; its power rail
// and TX/RX exact voltage/pin orientation require the carrier schematic.
SensirionI2cScd4x scd;
Adafruit_BME680 bme(&Wire);
Adafruit_AMG88xx amg;
ld2410 radar;
desk_robot_room::RadarSampleClock radar_sample_clock;
desk_robot_room::UsbEpochSync usb_epoch_sync;
bool scd_started = false;
bool scd_valid = false;
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
    // A bus error invalidates the old sample now, not after kScdStaleMs.
    // A healthy not-ready poll retains it only until that age limit.
    scd_valid = desk_robot_room::scd_sample_valid_after_poll(
        scd_valid, readiness_status, ready, measurement_valid);
  }
  const bool fresh = scd_valid && now - last_scd_ms <= kScdStaleMs;
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
    if (!bme_pending) bme_completed.invalidate();
    return;
  }
  const int remaining = bme.remainingReadingMillis();
  if (remaining > Adafruit_BME680::reading_complete) return;
  bme_pending = false;
  if (remaining != Adafruit_BME680::reading_complete || !bme.endReading()) {
    bme_completed.invalidate();
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
  // read() only drains the existing upstream bounded UART parser.
  // A static/moving echo is not authentication or a particular human.
  const bool connected = radar.isConnected() && radar_sample_clock.has_sample();
  Serial.print(F("\"ld2410c\":{\"valid\":")); jsbool(connected);
  if (connected) {
    Serial.print(F(",\"sample_ms\":"));
    Serial.print(radar_sample_clock.sample_ms());
    Serial.print(F(",\"presence\":")); jsbool(radar.presenceDetected());
    Serial.print(F(",\"stationary\":")); jsbool(radar.stationaryTargetDetected());
    Serial.print(F(",\"moving\":")); jsbool(radar.movingTargetDetected());
    Serial.print(F(",\"stationary_cm\":"));
    Serial.print(radar.stationaryTargetDistance());
    Serial.print(F(",\"moving_cm\":")); Serial.print(radar.movingTargetDistance());
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
  if (now - thermal_started_ms >= kThermalScanMaxMs ||
      !desk_robot_room::read_thermal_chunk(
          Wire, kAmgAddress, thermal_next_chunk,
          thermal_staging + 8U * thermal_next_chunk)) {
    thermal_scan_active = false;
    thermal_valid = false;
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
  scd.begin(Wire, SCD41_I2C_ADDR_62);  // 0x62, same address for SCD40
  // Sensirion's upstream example explicitly stops old measurement state.
  scd.stopPeriodicMeasurement();
  scd_started = scd.startPeriodicMeasurement() == 0;
  bme_started = bme.begin(kBmePrimary) || bme.begin(kBmeAlternate);
  if (bme_started) {
    bme.setTemperatureOversampling(BME680_OS_8X);
    bme.setHumidityOversampling(BME680_OS_2X);
    bme.setPressureOversampling(BME680_OS_4X);
    bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
    bme.setGasHeater(320, 150);
  }
  amg_started = amg.begin(kAmgAddress);
  Serial1.begin(256000);  // LD2410C, different UART from USB CDC Serial
  // Pinned ld2410 v0.2.2 otherwise blocks probing the optional radar
  // firmware for up to one second when the board is missing. Keep the
  // shared climate and thermal station independently bootable.
  radar.begin(Serial1, false);
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
  const bool radar_activity = radar.read();
  const uint32_t now = millis();
  // The pinned library reports connected for up to 100 ms after its last
  // valid packet. Preserve when UART activity was actually observed instead
  // of stamping cached target data with the later one-second report time.
  radar_sample_clock.observe(radar_activity, radar.isConnected(), now);
  bme_step(now); // no heater-time sleep; preserve 256000 baud radar service
  thermal_step(now); // one I2C chunk per loop, complete frame only
  if (now - last_report_ms >= kReportMs) {
    last_report_ms = now;
    report(now);
  }
}
