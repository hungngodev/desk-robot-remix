# One robot: firmware checked SIGNAL harness

**Not a finished protected charger or an electrically certified circuit.**
Generated from docs/hardware/full-feature-plan.json and the actual
BodyPins.h and head/sense/config.h symbols. Regenerate after any pin edit.
Signal-only list. Never infer a power source from a logic voltage.

| Source | Destination | Signal | Evidence |
| --- | --- | --- | --- |
| WROOM GPIO13 | left ULN2003 IN1 | 3.3V phase control | Source allocated |
| WROOM GPIO14 | left ULN2003 IN2 | 3.3V phase control | Source allocated |
| WROOM GPIO25 | left ULN2003 IN3 | 3.3V phase control | Source allocated |
| WROOM GPIO26 | left ULN2003 IN4 | 3.3V phase control | Source allocated |
| WROOM GPIO27 | right ULN2003 IN1 | 3.3V phase control | Source allocated |
| WROOM GPIO32 | right ULN2003 IN2 | 3.3V phase control | Source allocated |
| WROOM GPIO33 | right ULN2003 IN3 | 3.3V phase control | Source allocated |
| WROOM GPIO23 | right ULN2003 IN4 | 3.3V phase control | Source allocated |
| WROOM GPIO18 | MG90S lift signal | 3.3V PWM signal only | Source allocated |
| WROOM GPIO19 | MG90S jaw signal | 3.3V PWM signal only | Source allocated |
| XIAO GPIO2 TX | WROOM GPIO16 RX | UART 115200, 3.3V | Source allocated |
| WROOM GPIO17 TX | XIAO GPIO1 RX | UART 115200, 3.3V | Source allocated |
| XIAO GND | WROOM GND | Common logic reference; power path unverified | Source allocated |
| WROOM GPIO21 SDA + GPIO22 SCL | MPU6050 + 0x70 + 0x71 mux inputs | 3.3V I2C; actual breakout pullups need checking | Source allocated |
| WROOM GPIO34 | AT42QT1010 OUT | 3.3V input; external bias required on GPIO34 through GPIO39 | Source allocated |
| WROOM GPIO35 | NC bumper series OUT | 3.3V input; external bias required on GPIO34 through GPIO39 | Source allocated |
| MCP23017 GPB0 | optional reed switch | 3.3V input; closes LOW to GND | Source polled; physically unqualified |
| MCP23017 GPB1 | optional PIR output | 3.3V input; active HIGH | Source polled; physically unqualified |
| WROOM GPIO36 reserved | left 38kHz IR demodulator | Demodulated NEC burst input, external bias; ESP32 erratum | Bounded RMT decoder in source; NO physical receiver acceptance, do NOT wire yet |
| WROOM GPIO39 reserved | right 38kHz IR demodulator | Demodulated NEC burst input, external bias; ESP32 erratum | Bounded RMT decoder in source; NO physical receiver acceptance, do NOT wire yet |
| XIAO GPIO5 | SSD1306 SDA | 3.3V head signal | Source allocated |
| XIAO GPIO6 | SSD1306 SCL | 3.3V head signal | Source allocated |
| XIAO GPIO4 | MAX98357A BCLK | 3.3V head signal | Source allocated |
| XIAO GPIO7 | MAX98357A LRC | 3.3V head signal | Source allocated |
| XIAO GPIO8 | MAX98357A DIN | 3.3V head signal | Source allocated |
| XIAO onboard GPIO41 DIN + GPIO42 CLK | Sense PDM microphone | Integrated board pins, NOT connections to WROOM | Source allocated |
| XIAO GPIO9 reserved | RGB heart data | Driver not implemented; SD J3 physical conflict unresolved | Do NOT wire yet |
| Range TCA9548A 0x70 CH0 SDA/SCL | VL53L4CD (0x29) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Range TCA9548A 0x70 CH1 SDA/SCL | VL53L4CD (0x29) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Range TCA9548A 0x70 CH2 SDA/SCL | VL53L4CD (0x29) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Range TCA9548A 0x70 CH3 SDA/SCL | VL53L4CD (0x29) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Range TCA9548A 0x70 CH4 SDA/SCL | VL53L4CD (0x29) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Range TCA9548A 0x70 CH5 SDA/SCL | VL53L4CD (0x29) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Range TCA9548A 0x70 CH6 SDA/SCL | VL53L4CD (0x29) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Range TCA9548A 0x70 CH7 SDA/SCL | VL53L4CD (0x29) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH0 SDA/SCL | CAP1188 (0x28), MAX30102 paw pad (0x57) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH1 SDA/SCL | APDS9960 (0x39), AS5600 nose (0x36) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH2 SDA/SCL | ADS1115 (0x48) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH3 SDA/SCL | SHT41 (0x44), BMP280 (0x76) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH4 SDA/SCL | INA226 (0x40), MAX17048 (0x36) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH5 SDA/SCL | PN532 I2C (0x24), MCP23017 (0x20) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH6 SDA/SCL | AS5600 (0x36) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH7 SDA/SCL | AS5600 (0x36) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |

## Unresolved connections that prevent full robot assembly

* Matched protected 1S pack, fuse, NTC, polarity and discharge rating.
* Keyed recessed dock contacts, input current limit, charger netlist,
  true pack charging current and regulator peak current rating.
* Qualified power and ground distribution to motors, servos, XIAO,
  WROOM, speaker and 3.3V sensors. Never power actuators through MCU GPIO.
* XIAO external 5V/VBUS requires manufacturer-compliant diode or
  verified power-path isolation from USB before simultaneous USB use.
  NEVER directly tie robot boost 5V to laptop USB VBUS.
* XIAO Sense camera/SD expansion J3 must be physically isolated
  and continuity-checked before GPIO7/8 I2S and GPIO9 RGB use.
  SD card slot disabled and empty; verify shipped PCB revision.
* Reed/PIR now have slow MCP23017 GPIOB input source, freeing
  GPIO36/39 for dual IR. Real timing, optical baffles, RTC/ADC erratum
  filtering and final homing remain entirely unqualified.
* Breakout VCC and I2C pullups, connector pin order and cable gauge.
* Printed fit, local cliff geometry, audio and charger bench trials.

**Assembly readiness: NO. Firmware signal allocation only.**
