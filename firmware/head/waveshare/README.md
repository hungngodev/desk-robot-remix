# Waveshare ESP32-S3-CAM-OV5640 candidate head

**Optional fallback only. Keep the user's purchased XIAO Sense as the active
head.** This adapter has host checks but no completed build or hardware
acceptance record. It is not an additional required purchase.

Separate `--board waveshare` target; no physical audio/camera/voice-interruption
acceptance claimed. This is not Sense, Freenove or CoreS3 firmware. Confirm the
exact board/revision,16MB flash/8MB PSRAM and pin labels before wiring/flashing.

Reuses pinned Xiaozhi `waveshare/esp32-s3-cam` camera, CH32 reset/power sequence
and `BoxAudioCodec` hardware-reference path. Onboard ES8311/ES7210 supplies
24kHz capture/playback, microphone plus physical speaker reference, resampled
together to16kHz MR by the existing audio service. Device AEC is required by
build guards and an exact-board reversible Kconfig whitelist addition. No new
DSP codec, playback-reference buffer or second microphone is implemented here.

- Onboard control/camera/audio bus: I2C1, SDA8/SCL7. Camera uses this existing bus.
- Owned SSD1306: **separate I2C0 SDA1/SCL2** on the unused LCD connector,3.3V
  logic and ground. No SPI LCD attached. OV5640 and OLED may both address0x3C;
  do not join these buses. Check connector orientation/pin numbering physically.
- Body UART1: TX43→WROOM RX16, RX44←WROOM TX17,1152008N1,3.3V/common ground.
  GPIO43/44 appear on the board header. Application console is USB Serial/JTAG
  only, no secondary UART console. Native USB19/20 remain untouched.
- ROM may still emit reset/programming bytes before app UART routing. Do not
  burn eFuses to silence it. Verify traces and body-disarmed behavior across
  power/reset/reflash; boot output must never authorize motion.
- Existing authenticated bridge/camera locks and fail-closed empty-token behavior
  remain. No raw motor authority is added; body stop/arming policy is unchanged.

Generic and private Waveshare build commands include the existing `hiesp` wake
model. Other generic board commands retain their previous disabled wake setting.
Wake-phrase detection is not ordinary-speech interruption. Realtime input/AEC
must be tested with the Mac/server abort path, current decoder/playback queues,
double talk, speaker-only false interruptions, motor/camera/Wi-Fi load and
reconnect. Button control remains available for development/recovery only and
does not satisfy the user's required voice-interruption gate. No hardware flashed.

Upstream hardware pin reference:
[pinned board](https://github.com/78/xiaozhi-esp32/tree/c435f99a88066029ec2dbd2d758c8cc9d051565b/main/boards/waveshare/esp32-s3-cam).
Physical fit, speaker/mic/reference levels, supply and case mounts remain open.
