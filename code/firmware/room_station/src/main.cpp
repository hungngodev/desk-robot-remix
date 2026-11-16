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

#ifndef ROOM_SOIL_FITTED
#define ROOM_SOIL_FITTED 0
#endif

namespace {
constexpr uint32_t kReportMs = 1000;
constexpr uint32_t kScdStaleMs = 8500;
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
bool scd_started = false;
bool scd_valid = false;
bool bme_started = false;
bool amg_started = false;
uint16_t co2_ppm = 0;
float scd_temp = 0, scd_humidity = 0;
uint32_t last_scd_ms = 0;
uint32_t last_report_ms = 0;
uint32_t sequence = 0;
float thermal[AMG88xx_PIXEL_ARRAY_SIZE] = {};

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
    if (scd.getDataReadyStatus(ready) == 0 && ready) {
      uint16_t ppm = 0;
      float t = 0, rh = 0;
      if (scd.readMeasurement(ppm, t, rh) == 0 &&
          ppm > 0 && ppm <= 50000 && finite_temperature(t) &&
          isfinite(rh) && rh >= 0 && rh <= 100) {
        co2_ppm = ppm;
        scd_temp = t;
        scd_humidity = rh;
        last_scd_ms = now;
        scd_valid = true;
      } else {
        scd_valid = false;
      }
    }
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
void bme_observation(uint32_t now) {
  bool valid = false;
  if (bme_started && bme.performReading()) {
    valid = finite_temperature(bme.temperature)
            && isfinite(bme.humidity) && bme.humidity >= 0
            && bme.humidity <= 100
            && isfinite(bme.pressure) && bme.pressure > 0
            && isfinite(bme.gas_resistance) && bme.gas_resistance >= 0;
  }
  Serial.print(F("\"bme688\":{\"valid\":")); jsbool(valid);
  if (valid) {
    Serial.print(F(",\"sample_ms\":")); Serial.print(now);
    Serial.print(F(",\"temp_c\":")); number(bme.temperature);
    Serial.print(F(",\"humidity_pct\":")); number(bme.humidity);
    Serial.print(F(",\"pressure_pa\":")); number(bme.pressure, 0);
    Serial.print(F(",\"gas_ohms\":")); number(bme.gas_resistance, 0);
    // Gas resistance is NOT a calibrated VOC ppm or indoor air quality index.
  }
  Serial.print('}');
}
void radar_observation(uint32_t now) {
  // read() only drains the existing upstream bounded UART parser.
  // A static/moving echo is not authentication or a particular human.
  const bool connected = radar.isConnected();
  Serial.print(F("\"ld2410c\":{\"valid\":")); jsbool(connected);
  if (connected) {
    Serial.print(F(",\"sample_ms\":")); Serial.print(now);
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
  // Raw ADC is NOT moisture percentage without probe and soil calibration.
  jsbool(true);
  Serial.print(F(",\"sample_ms\":")); Serial.print(now);
  Serial.print(F(",\"raw_adc\":")); Serial.print(analogRead(A0));
#else
  (void)now;
  jsbool(false);
#endif
  Serial.print('}');
}
void thermal_observation(uint32_t now) {
  bool valid = amg_started;
  if (valid) {
    amg.readPixels(thermal);
    for (float temp : thermal) {
      if (!finite_temperature(temp)) { valid = false; break; }
    }
  }
  Serial.print(F("\"amg8833\":{\"valid\":")); jsbool(valid);
  if (valid) {
    Serial.print(F(",\"sample_ms\":")); Serial.print(now);
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
  radar.begin(Serial1);
#if ROOM_SOIL_FITTED
  analogReadResolution(12);
#endif
}
void loop() {
  radar.read();
  const uint32_t now = millis();
  if (now - last_report_ms >= kReportMs) {
    last_report_ms = now;
    report(now);
  }
}
