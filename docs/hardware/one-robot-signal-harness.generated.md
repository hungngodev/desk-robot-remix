# One robot: firmware checked SIGNAL harness

**Not a finished protected charger or an electrically certified circuit.**
Generated from docs/hardware/full-feature-plan.json and the actual
BodyPins.h and head/sense/config.h symbols. Regenerate after any pin edit.
Signal-only list. Never infer a power source from a logic voltage.

**Motor variants are mutually exclusive:** `esp32_full` uses ULN2003 steppers;
`esp32_dc_full` uses DRV8833 DC motors. Never connect both motor drivers.

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
| WROOM GPIO25 + GPIO26 | left DRV8833 AIN1/AIN2 (DC FULL only) | 3.3V motor PWM signals, alternative to left ULN2003 | Guarded DC profile; physical load unqualified |
| WROOM GPIO27 + GPIO32 | right DRV8833 BIN1/BIN2 (DC FULL only) | 3.3V motor PWM signals, alternative to right ULN2003 | Guarded DC profile; physical load unqualified |
| WROOM GPIO23 (DC only; same as STEP right coil 4) | CD74HC123 channel 2 B rising-edge input | CPU-only 15ms toggles, 3.3V; no LEDC, pull LOW at boot | Source in esp32_dc_watchdog_lab and esp32_dc_integrated_lab; nSLEEP gate unqualified |
| WROOM GPIO18 | MG90S lift signal | 3.3V PWM signal only | Source allocated |
| WROOM GPIO19 | MG90S jaw signal | 3.3V PWM signal only | Source allocated |
| XIAO GPIO2 TX | WROOM GPIO16 RX | UART 115200, 3.3V | Source allocated |
| WROOM GPIO17 TX | XIAO GPIO1 RX | UART 115200, 3.3V | Source allocated |
| XIAO GND | WROOM GND | Common logic reference; power path unverified | Source allocated |
| Recessed keyed 5V dock contacts with independent current limit | BQ24075 IN pin 13 with local bypass | NO permanently live exposed pogo pads; no direct battery/boost connection | TI BQ24075 Rev N reference only; physical dock wiring HOLD |
| BQ24075 OUT pins 10/11: battery-dependent 3V to 5.6V | Rated buck-boost VIN, 5V fixed regulated output | Pololu S13V30F5 2.8V to 22V is voltage-range reference ONLY | Actual 3V INPUT max safe current, 5V ripple and thermals HOLD |
| BQ24075 BAT pins 2/3, through 5mOhm >=2W Kelvin shunt | Protected 1S battery PACK+ at removable rated connector | INA226 IN+ on CHARGER BAT side; IN- on PACK+ side | Positive current = PACK CHARGE; real thermal/PCM/wire fit UNQUALIFIED |
| Protected PACK- and 10k NTC lead | Charger VSS and TS pin 1 respectively | NTC returns to PACK-; no 10k fixed TS bypass in active charge circuit | Exact NTC beta, pack pin order and thermal abort fault TEST REQUIRED |
| INA226 0x40 on accessory TCA9548A 0x71 CH4 | Kelvin sense across protected pack current shunt | Opt-in signed 5mOhm current, fresh I2C seq, 3.3V logic | Not physical calibration; NO software charge enable or approval |
| Two independent normally closed dock stop switches | MCP23017 0x20 GPA0/GPA1 via 3.3V pullups | Each closes to GND; open/HIGH on either input blocks motion | Mandatory source interlock; actual switches and fault behavior HOLD |
| BQ24075 open drain PGOOD and CHG | MCP23017 0x20 GPA2/GPA3 via 3.3V pullups | Read-only; PGOOD=LOW input good, CHG=LOW charge indicated | Indicator not battery current, status HIGH-Z when disconnected |
| Fused rated 5V system boost through head branch Schottky anode | XIAO Sense 5V input at Schottky cathode | External to head ONLY, reversed current blocked from XIAO USB | Seeed official XIAO external 5V diode rule; exact diode current/heat HOLD |
| Fused rated 5V motor/servo branch with local >=470uF rated bulk | MG90S lift/grip and motor driver VM power | Direct rated 5V branch, NEVER via XIAO 3V3 or USB/diode | 470uF documented in cgro00 V2 servo wiring, NOT sufficient-rating proof for this robot |
| Fused rated 5V audio branch, independent of XIAO diode | MAX98357A VIN with local 0.1uF + 10uF decoupling | Common ground; amplifier outputs floating differential | MAX98357A manufacturer datasheet bypass; current/acoustic tests HOLD |
| WROOM GPIO21 SDA + GPIO22 SCL | MPU6050 (0x68) + 0x70 + 0x71 mux inputs | 3.3V I2C; actual breakout pullups need checking | Source allocated |
| 3.3V logic via appropriate pullups | Both TCA9548A active-LOW RESET inputs | Passive HIGH; no WROOM GPIO4 or other MCU RESET drive | Exact breakout and startup levels HOLD |
| TCA9548A address straps | 0x70 ranges and 0x71 accessories | 0x70 A2/A1/A0 LOW; 0x71 A2/A1 LOW, A0 HIGH | Verify actual board address straps before power-up |
| AT42QT1010 OUT | WROOM GPIO34 | 3.3V active-HIGH capacitive input; external bias required on GPIO34 through GPIO39 | Source allocated |
| 3.3V external pullup node + NC bumper switch series -> GND | WROOM GPIO35 | 3.3V passive NC input (HIGH on open/fault, LOW when seated); external bias required on GPIO34 through GPIO39 | Source allocated |
| Optional reed switch to GND (with external 3.3V pullup) | MCP23017 GPB0 | 3.3V input; closes LOW to GND | Source polled; physically unqualified |
| Optional PIR output | MCP23017 GPB1 | 3.3V input; active HIGH | Source polled; physically unqualified |
| DRV8833 nFAULT (DC only) | MCP23017 GPB3 | Open drain active LOW; 4.7k 3.3V pullup at driver, 100k pulldown at expander | Disconnected lead must read LOW/fault; carrier and fault response HOLD |
| MCP23017 GPB2 | CD74HC123 rising-edge haptic trigger (1B pin 2) | 3.3V lab-only edge, not motor current; external defined LOW at boot | Source gated in esp32_full_haptic_lab and esp32_dc_integrated_lab; physical one-shot NOT qualified |
| Regulated 3.3V logic rail | CD74HC123 VCC pin 16 | 100nF local bypass to ground; HC not HCT | Haptic bench candidate only |
| Common logic and motor return | CD74HC123 GND pin 8 and AO3400 source | Shared reference; motor current stays off logic signal wires | Haptic bench candidate only |
| Logic LOW / HIGH | CD74HC123 1A pin 1 LOW / 1CLR pin 3 HIGH | GPB2 externally pulled LOW; verify startup and reset | Haptic bench candidate only |
| 180kOhm timing resistor to 3.3V | CD74HC123 1RxCx pin 15 | 1uF candidate capacitor between pin 15 and 1Cx pin 14 | Timing at actual 3.3V NOT measured |
| CD74HC123 1Q pin 13 | AO3400 gate through series resistor | External gate pulldown; inverted Q pin 4 unused | Haptic bench candidate only |
| Rated regulated 3V motor supply | Coin motor positive; motor negative to AO3400 drain | Flyback diode cathode to motor positive, anode to drain | Current limit, stall, heat and independent pulse termination HOLD |
| left 38kHz IR demodulator | WROOM GPIO36 reserved | Demodulated NEC burst input, external bias; ESP32 erratum | Bounded RMT decoder in source; NO physical receiver acceptance, do NOT wire yet |
| right 38kHz IR demodulator | WROOM GPIO39 reserved | Demodulated NEC burst input, external bias; ESP32 erratum | Bounded RMT decoder in source; NO physical receiver acceptance, do NOT wire yet |
| XIAO GPIO5 | SSD1306 SDA | 3.3V head signal | Source allocated |
| XIAO GPIO6 | SSD1306 SCL | 3.3V head signal | Source allocated |
| XIAO GPIO4 | MAX98357A BCLK | 3.3V head signal | Source allocated |
| XIAO GPIO7 | MAX98357A LRC | 3.3V head signal | Source allocated |
| XIAO GPIO8 | MAX98357A DIN | 3.3V head signal | Source allocated |
| Rated, isolated 5V audio power rail | MAX98357A VDD/VIN | 5V for current 2W speaker; never parallel unisolated USB VBUS | Design allocation only; audio rail peaks, clipping and heat HOLD |
| MAX98357A OUTP and OUTN | 8 ohm 2 W CS20-02P110-04-1X + and - | Bridge tied differential outputs; NEVER connect either output to GND | Manufacturer 5V 8ohm nominal 1.8W; real carrier/rectangular baffle heat HOLD |
| XIAO Sense onboard camera | Internal camera data, clocks and SCCB | Stock integrated camera; no external harness connection | Source allocation only; physical camera and SD isolation HOLD |
| XIAO onboard GPIO41 DIN + GPIO42 CLK | Sense PDM microphone | Integrated board pins, NOT connections to WROOM | Source allocated |
| XIAO GPIO9 reserved | RGB heart data | Xiaozhi WS2812 driver compiled only with explicit opt-in; SD J3 and 5V level buffer still unqualified | Do NOT wire yet |
| Rated regulated 3.3V expansion rail | eight GY-530 VL53L0X VIN pins and TCA9548A 0x70 VCC | 3.3V ONLY in selected design; 5V VIN can raise SDA/SCL to 5V | Exact seller board pullup and every upstream/downstream HIGH rail UNTESTED |
| Range TCA9548A 0x70 CH0 SDA/SCL | VL53L0X (0x29), floor front left (critical cliff) | WROOM 3.3V logic ONLY; carrier VIN and external SDA/SCL pullup voltage UNKNOWN; 5V exposure forbidden | Unqualified carrier; DO NOT ENERGIZE before voltage checks |
| Range TCA9548A 0x70 CH1 SDA/SCL | VL53L0X (0x29), floor front right (critical cliff) | WROOM 3.3V logic ONLY; carrier VIN and external SDA/SCL pullup voltage UNKNOWN; 5V exposure forbidden | Unqualified carrier; DO NOT ENERGIZE before voltage checks |
| Range TCA9548A 0x70 CH2 SDA/SCL | VL53L0X (0x29), floor rear left (critical cliff) | WROOM 3.3V logic ONLY; carrier VIN and external SDA/SCL pullup voltage UNKNOWN; 5V exposure forbidden | Unqualified carrier; DO NOT ENERGIZE before voltage checks |
| Range TCA9548A 0x70 CH3 SDA/SCL | VL53L0X (0x29), floor rear right (critical cliff) | WROOM 3.3V logic ONLY; carrier VIN and external SDA/SCL pullup voltage UNKNOWN; 5V exposure forbidden | Unqualified carrier; DO NOT ENERGIZE before voltage checks |
| Range TCA9548A 0x70 CH4 SDA/SCL | VL53L0X (0x29), front obstacle (critical obstacle) | WROOM 3.3V logic ONLY; carrier VIN and external SDA/SCL pullup voltage UNKNOWN; 5V exposure forbidden | Unqualified carrier; DO NOT ENERGIZE before voltage checks |
| Range TCA9548A 0x70 CH5 SDA/SCL | VL53L0X (0x29), left obstacle (read-only observation; no movement authority) | WROOM 3.3V logic ONLY; carrier VIN and external SDA/SCL pullup voltage UNKNOWN; 5V exposure forbidden | Unqualified carrier; DO NOT ENERGIZE before voltage checks |
| Range TCA9548A 0x70 CH6 SDA/SCL | VL53L0X (0x29), right obstacle (read-only observation; no movement authority) | WROOM 3.3V logic ONLY; carrier VIN and external SDA/SCL pullup voltage UNKNOWN; 5V exposure forbidden | Unqualified carrier; DO NOT ENERGIZE before voltage checks |
| Range TCA9548A 0x70 CH7 SDA/SCL | VL53L0X (0x29), rear obstacle (read-only observation; no movement authority) | WROOM 3.3V logic ONLY; carrier VIN and external SDA/SCL pullup voltage UNKNOWN; 5V exposure forbidden | Unqualified carrier; DO NOT ENERGIZE before voltage checks |
| Accessory TCA9548A 0x71 CH0 SDA/SCL | CAP1188 (0x29), MAX30102 paw pad (0x57) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH1 SDA/SCL | APDS9960 (0x39), AS5600 nose (0x36) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH2 SDA/SCL | ADS1115 (0x48) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH3 SDA/SCL | SHT41 (0x44), BMP280 (0x76) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH4 SDA/SCL | INA226 (0x40), MAX17048 (0x36) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH5 SDA/SCL | PN532 I2C (0x24), MCP23017 (0x20) | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH6 SDA/SCL | AS5600 (0x36), left wheel rotation | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |
| Accessory TCA9548A 0x71 CH7 SDA/SCL | AS5600 (0x36), right wheel rotation | Isolated 3.3V I2C lane; separately qualify GND/VCC | Source driver; physical carrier unqualified |

## Unresolved connections that prevent full robot assembly

* Matched protected 1S pack, fuse, NTC, polarity and discharge rating.
* Keyed recessed dock contacts, input current limit, charger netlist,
  true pack charging current and regulator peak current rating.
* Qualified power and ground distribution to motors, servos, XIAO,
  WROOM, speaker and 3.3V sensors. Never power actuators through MCU GPIO.
* Source-reused XIAO power isolation: Seeed 5V external input needs
  Schottky anode on fused boost and cathode on XIAO 5V pin.
  cgro00/desk-robot V2 docs use 1N5817 + 470uF 5V servo bulk;
  its two-servo supply rating is NOT sufficient evidence for our motors.
* XIAO external 5V/VBUS requires manufacturer-compliant diode or
  verified power-path isolation from USB before simultaneous USB use.
  NEVER directly tie robot boost 5V to laptop USB VBUS.
* XIAO Sense camera/SD expansion J3 must be physically isolated
  and continuity-checked before GPIO7/8 I2S and GPIO9 RGB use.
  SD card slot disabled and empty; verify shipped PCB revision.
* DC-only GPIO23 heartbeat is NOT the DRV8833 motor driver nSLEEP.
  It needs the independent second HC123 channel, verified Q timeout
  and a fail-LOW interface against any onboard VM-to-nSLEEP pullup.
* Haptic MCP23017 GPB2 drives only a generic HC123 one-shot trigger,
  not the coin motor. Verify active-HIGH edge, 3.3V rail, timed Q and
  low-side MOSFET/flyback current; production effect stays disabled.
* Reed/PIR now have slow MCP23017 GPIOB input source, freeing
  GPIO36/39 for dual IR. Real timing, optical baffles, RTC/ADC erratum
  filtering and final homing remain entirely unqualified.
* Breakout VCC and I2C pullups, connector pin order and cable gauge.
* All eight VL53L0X carriers: identify PCB revision and verify VIN
  plus upstream/downstream SDA/SCL HIGH voltages with motors OFF.
  Do NOT energize any ToF lane until 5V WROOM exposure is excluded.
* Printed fit, local cliff geometry, audio and charger bench trials.

**Assembly readiness: NO. Firmware signal allocation only.**
