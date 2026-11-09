# Complete HTML and repo feature traceability register

**Purpose:** Prevent any behavioral, sensor, accessory, game or research idea from vanishing when the robot is integrated. All 23 HTML sections and their named idea families are represented. This is an inventory of requirements and *research candidates*, **not a claim that every module is owned, electrically compatible, purchased, implemented or physically tested**. Details, citations and original URLs remain in the original 1.1MB HTML and [source map](../source-map.md); see [reuse register](reuse-register.md) and [system contract](system-contract.md).

**Status interpretation:** `REQUIRED` is a user-visible hard goal that may not be deferred out of the final product. `RESERVE NOW` means leave physical/software extension accommodation before assembling, not that the module must be purchased. `EXPANSION` means fully recorded, with a planned adapter/test but separate cost/fit approval. `REFERENCE` means concept only. `REJECTED FOR SAFETY` cannot be implemented as described. `EVALUATE` is an upstream or tuning candidate awaiting independent proof. Hybrid statuses reflect a required *behavior* with an optional *sensor implementation*. The $50 hard cap and small body make all listed experimental physical modules simultaneously installed an unproven, almost certainly incompatible configuration; see [decision gate](decisions-before-hardware.md).

## A. Live HTML sections 1–16 and repo requirements

| ID | Idea or requirement | Design status | Day-zero reservation, constraint, or proof required |
| --- | --- | --- | --- |
| `F001` | Complete robot form | REQUIRED | One low tracked 28BYJ SMARS core, fixed expressive Sense head, front two-servo closing lift/gripper, five independent copies with different costumes |
| `F002` | Architecture and original parts | REQUIRED | Body WROOM local safety, Sense camera/mic/OLED/speaker, Mac central AI; count actually owned parts |
| `F003` | Seven stages vs day-zero architecture | REQUIRED | The seven original build tasks remain, but all interfaces/holes/requirements are locked before Stage 1 physical work |
| `F004` | Source and historical status honesty | REQUIRED | Do not call compiled firmware, mock robot or draft HTML a tested build |
| `F005` | Delivered budget | REQUIRED | Full $50 cap including reported Sense purchase; cannot accept unpriced extras or silently swap to unsafe cheap power |
| `F006` | MAX30102 paw heart pad | RESERVE NOW | HTML claims about five purple units; verify actual stock and breakout rails; WROOM bus not Sense PDM41/42; user opt-in and nonmedical |
| `F007` | IP5306 architecture A power | BENCH CANDIDATE | Exact board revision, rated output, 1S chemistry/protection, cell and charger; no assumption that chip limit equals module limit |
| `F008` | Power sequencing S1–S8 and low-voltage ladder | REQUIRED DESIGN | Load priority, stepper/servo starts, sag response, cutoff/restart and explicit safe payload behavior measured under system load |
| `F009` | Bulk and local decoupling | REQUIRED DESIGN | Capacitance values from measurement, short power leads, fuse/connector/wire ratings; not a replacement for sufficient supply |
| `F010` | Stepper phases/ramp and gear truth | REQUIRED | Measured phase order, ratio/travel/backlash, speed/acceleration/coils-off modes; current code effective 160 steps/s |
| `F011` | Servo bank 30-minute grading and grades A–X | REQUIRED METHOD | Count and inspect nominal MG90S, measure range, stall/heat/fit/grip; reject failed units before mounted prints |
| `F012` | Gripper fork as scoop; bow on keys, candy wrappers | REQUIRED | Existing Bluino/SMARS lift + 2 positional servos, key/candy strategies, real 8/10 each trials |
| `F013` | Gripper current signatures and sensing ladder | RESERVE NOW | Optional INA219 shunt, contact switch, FSR, camera verification, stall/force readouts; do not call current signature proven grip |
| `F014` | Four corner downward ToFs, one forward, mux | REQUIRED | Concealed views and measured stop geometry; VL6180X obsolete so qualify updated short-range part before fleet commitment |
| `F015` | Continuous ToF polling and 40ms proposed scan | MEASURE | Bounded mux selection/status/timestamp, quality and freshness; no unmeasured 40ms guarantee |
| `F016` | Cliff classifier and fail-closed behavior | REQUIRED | No blind reverse, sensor degradation drive or auto-resume, local USB recovery only and operator arming |
| `F017` | Owned head touch + boot calibration | REQUIRED | AT42QT1010 through shell, tap/hold patterns, false activation, touch during motion pauses |
| `F018` | BerryIMU revision and handling | REQUIRED | Detect actual older board chip IDs; tilt, shake, suspected pickup combined with floor context; motor vibration rejection |
| `F019` | Optional force/vibration/magnet handling | RESERVE NOW | FSR402, piezo, Hall/reed, SW-18010P and pet/belly accessory interfaces; no assumed stock |
| `F020` | Audio RIO AEC and actual user barge-in | REQUIRED | Software reference calibration, double-talk; 19/20 audible stop ≤500ms and 18/20 new request; echo only 10min zero false |
| `F021` | Erle/latency report targets | MEASURE | HTML's 15–25dB ERLE and 18/20 700ms rates are not accepted proof; record measured metrics without weakening canonical A2 |
| `F022` | Flushing network, Mac queue, ESP DMA | REQUIRED | Epoch/generation IDs, FLUSH through transport and DMA, no obsolete sentence resumed after reconnect |
| `F023` | RoboEyes face choice and 0.96in fit | SOURCE GATE | HTML calls selected; repo still uses stock Xiaozhi UI; compare GPL3 vs MIT alternative before final face integration |
| `F024` | Cozmars/Sparky/Fetch style and packaging | REQUIRED DESIGN | Round retro TV + Cozmo/Vector, owned OLED, removable cosmetics, no extra head servo silently |
| `F025` | Three Mac processes, Motion Gateway separation | ARCHITECTURE CANDIDATE | Structural model privilege boundary required; exact number of processes measured, not dogma |
| `F026` | Shared MLX Whisper turbo and circuit breaker | EVALUATE | Proposed Apple Silicon shared model, priority class, fallback to whisper.cpp; never assume measured fleet performance |
| `F027` | Kokoro 82M, voices and sentence streaming | REQUIRED CAPABILITY | Five distinct voices, streaming, first chunk latency under actual Mac contention; fallback provider behind same interface |
| `F028` | Mac LLM/VLM selection and two call shapes | REQUIRED | Fast textual turn and image-grounded scene turn; local-first; vision on fresh event, not each frame |
| `F029` | Speaker lease, event clustering, Mac efuse IDs | REQUIRED + CANDIDATE | Single speaker; dedup five observations; manual IDs currently real, MAC efuse provisioning optional qualified future |
| `F030` | Per-robot memory single writer | REQUIRED | Private persistence, provenance, identity isolation, peer hearsay, corruption and restart tests |
| `F031` | Pipecat workers, MQTT Mosquitto, UDP/WS | EVALUATE | Do not stack simultaneous owners or require new broker without proven benefit; prefer existing server and adapters |
| `F032` | Proactive pushed camera events | REQUIRED | Fresh scene events without a spoken prompt, dedup, semantic confirmation, conditional new speech, camera/mic simultaneity |
| `F033` | Utility activity scorer and personality drives | REQUIRED | Mac deterministic activity owner; hard stop/quiet/speech priorities, small LLM intent only, curiosity/boredom/rest/social |
| `F034` | Ambient sound events and one RGB pixel | RESERVE NOW | Double clap attention, triple clap stop, whistle bands, self-sound filtering, no acoustic event may arm |
| `F035` | Fleet play and ongoing peers | REQUIRED | Distinct persistent characters, digital peer exchange, invitations, ten turns, social play, one speaker initially |
| `F036` | AprilTag localization and world anchors | EXPANSION | Existing detector libraries, fiducial cards and measured pose; not required to assert precise location from one camera |
| `F037` | Self-docking and OOMWOO patterns | EXPANSION | Actual charger mechanics, fiducials, safe approach, contact isolation; no automatic docking until separately proven |
| `F038` | Health freshness ladder | REQUIRED | Treat stale sensor data as fault; health from timestamps, successful reads and model confidence, not a plausible old value |
| `F039` | Research links landing pages and tutorials | PRESERVE | All HTML library sections cross-reference the source map and reuse register; reject conclusions not supported by code |

## B. Proactive experience, conversation, perception, memory and peer play

| ID | Idea or requirement | Design status | Day-zero reservation, constraint, or proof required |
| --- | --- | --- | --- |
| `B001` | Camera noticed person/hand/object independently | REQUIRED | Fresh event without button, prompt or user speech |
| `B002` | Scene change and actual semantic interpretation | REQUIRED | VLM reasons from evidence; label uncertainty and reject stale frame |
| `B003` | Repeated scene suppression and cooldown | REQUIRED | Dedup semantic/fingerprint at robot and fleet levels, enforce speech lease |
| `B004` | Contextually initiated speech | REQUIRED | Comments about a newly observed and relevant event; no generic scheduled greetings as substitute |
| `B005` | Routine independent activity | REQUIRED | Curiosity, inspecting, attention, social invitations, rest and silent stillness as selectable activities |
| `B006` | Periodic activity reconsideration | REQUIRED | Configurable 30–90s initial heuristic; vetoes and false trigger tests |
| `B007` | Group speech cooldown | REQUIRED | Initial at most 1 unsolicited group spoken initiation per 120s |
| `B008` | Live natural speech barge-in and double talk | REQUIRED | People speak over TTS; output flush and correctly captured first words |
| `B009` | No false self hearing | REQUIRED | 10min speech-only validation, motor/ambient noise, playback reference |
| `B010` | Speech-first ownership and quiet mode | REQUIRED | Quiet cancels pending spontaneous output, pauses movement; reply to user allowed |
| `B011` | Individual character, voice and memory | REQUIRED | Five distinct IDs/personas and remembered experiences with direct-vs-peer provenance |
| `B012` | Long-term memories and preference evolution | REQUIRED | Explicit user preferences, recent events, bounded private durable history, no invented facts |
| `B013` | Peer conversations and social games | REQUIRED | Digitally routed events, one audible voice, one movement source initially, coalescing |
| `B014` | Spontaneous peer invitations | REQUIRED | Occasional respectful invitations with distinct moods and turn limits |
| `B015` | Ongoing exploration until paused | REQUIRED | Operator-enabled continuing session, no timed reauthorization after 120/300s; bounded pulse + watchdog |
| `B016` | Person and object reactions via eyes | REQUIRED | Animated gaze toward evidence without needing to talk |
| `B017` | Touch/hold/petting reaction | REQUIRED | Head touch, handling fused, no touch gesture grants motor |
| `B018` | Music and ambient sound awareness | RESERVE NOW | Existing mic plus AEC/noise gate; no additional microphone necessary until directionality requirement |
| `B019` | Contextual observation heartbeat | REQUIRED | Send only fresh image when idle, not during user/model/tool session |
| `B020` | Activity cancellation and memory of interruption | REQUIRED | Generation/epoch cleanup, old completion cannot mark new session idle |
| `B021` | Emotion Lab simulator mapping | REFERENCE ONLY | Use its ideas for moods but do not copy old cliff retreat or fake spatial hearing |
| `B022` | Big Five to PAD affect; WASABI boredom spring | EVALUATE | Proposed personality math from HTML; values are simulated character policy, not measured feelings |
| `B023` | Self-perception confirmation loops | EXPANSION | Check generated beep/vibration with mic/IMU if source quality supports, not physical health diagnosis |
| `B024` | Camera attention motion centroids and stability | REUSE CANDIDATE | From Xiaozhi Desk Robot and Google's camera poller; correct self-motion artifacts |
| `B025` | Object pickup verification | REQUIRED | Vision + physical calibrated choreography; 8/10 real keys and candy separately |
| `B026` | Push-notification speech scheduling | REQUIRED | Events wait when speaker busy, not unsolicited mid-turn collision |
| `B027` | Optional cloud reasoning | OPTIONAL | Opt-in separate keys and cost telemetry; Mac local-first remains default |
| `B028` | Desk-connected contextual input | EXPANSION | User consent: PC activity, coding-agent state, calendar/reminders, weather, MCP tools; don't spy on workstation |
| `B029` | Social continuity and games spanning days | EXPANSION | Persistent pet stories, desk RPG and cross-robot evolving game state with bounded memory |
| `B030` | Independent reaction when Mac offline | REQUIRED | Local face/busy/fault responsiveness; never pretend offline LLM is running |

## C. Sensor ideas explicitly named in the research library

| ID | Idea or requirement | Design status | Day-zero reservation, constraint, or proof required |
| --- | --- | --- | --- |
| `S001` | VL6180X four downward | REQUIRED ROLE, PART RESEARCH | ST obsolete; qualify supported part and correct 4-corner geometry |
| `S002` | VL53L0X forward | REQUIRED | Separate obstacle view; 0x29 on mux, no all-side coverage |
| `S003` | VL53L1X alternative | COMPARISON | Different near-range constraints; not universal fix |
| `S004` | VL53L4CD short-range replacement | QUALIFY SAMPLE | Vendor ULD and ST migration approach; cost and software/ranging trials |
| `S005` | TCA9548A I2C switch | REQUIRED | Four floor + forward on channels 0–4, channels 5–7 reserved; bus health |
| `S006` | TCRT5000 reflectance | ALTERNATIVE EXPERIMENT | ~millimeter height, surface sensitive; not equivalent drop-in 4-corner ToF |
| `S007` | Pololu QTR reflectance | ALTERNATIVE EXPERIMENT | Low-mounted calibrated floor alternative, not automatic replacement |
| `S008` | AT42QT1010 cap touch | REQUIRED | Owned breakout; body GPIO34; check shield/touch through case |
| `S009` | Copper tape capacitive petting | REFERENCE | Use only with known capacitance electronics and ESD handling |
| `S010` | TTP223 touch | ALTERNATIVE | No new purchase if owned AT42QT1010 meets requirement |
| `S011` | MPR121 twelve-zone touch | EXPANSION | I2C 0x5A; zone harness, touch case, code and power budget |
| `S012` | FSR402 force strip | EXPANSION | Force/belly/grip event, analog ADC front end and calibration; not precision force control |
| `S013` | Piezo knock sensor | EXPANSION | Knock recognition; analog protection and motor vibration suppression |
| `S014` | SW-18010P vibration switch | VERIFY STOCK | HTML claims 2, repo has no confident model count; digital contact and debounce |
| `S015` | BerryIMU older multi-sensor | REQUIRED | Owned likely V1, actual chip/addresses/rails must be identified; accel + gyro |
| `S016` | MPU6050 IMU | ALTERNATIVE | Older research only, don't silently buy if BerryIMU works |
| `S017` | LSM6DS3TR-C six-axis IMU | CONDITIONAL | Replacement only after owned BerryIMU test fails |
| `S018` | GY-61 accelerometer | OPTIONAL STOCK | Cannot replace gyro-assisted handling fusion by itself |
| `S019` | QMC5883L magnetometer | EXPANSION | Yaw/reference demo, not track odometry |
| `S020` | AS5600 magnetic angle | EXPANSION | Magnetic knob/pose feedback; mount/magnet and bus conflict check |
| `S021` | Hall sensor + magnets/reed switch | EXPANSION | Hats, food, board games, proximity flags; no fabricated precise localization |
| `S022` | RC522 RFID reader | EXPANSION | Identified magnetic accessories/game tokens; SPI interface and power budget |
| `S023` | PN532 NFC | EXPANSION | Alternative token identity, explicit bus and range test |
| `S024` | MAX30102 pulse sensor | OPT-IN EXPANSION | Breakout/logic rails, WROOM I2C not Sense mic, nonmedical heartbeat petting |
| `S025` | BLE heart rate strap | OPT-IN EXPANSION | External opt-in data rather than onboard inference |
| `S026` | MR60BHA1 breathing radar | EXPANSION | Human-aware radar, consent, UART/power and vendor driver |
| `S027` | LD2410 mmWave presence | EXPANSION | Presence but not person identity/bearing; different rail/harness |
| `S028` | AM312 mini PIR | OPTIONAL STOCK | Human movement detection; no location or reliable stationary detection |
| `S029` | WiFi CSI presence | RESEARCH | Radio firmware/calibration, no guaranteed person distance or direction |
| `S030` | APDS9960 gesture/proximity/color/light | EXPANSION | I2C 0x39; different job from floor ToF and BerryIMU |
| `S031` | BH1750 ambient light | EXPANSION | Existing lighting ideas; I2C 0x23/0x5c chosen address |
| `S032` | TCS34725 dedicated RGB color | EXPANSION | Alternative to APDS color channel |
| `S033` | AS7341 spectral sensor | RESEARCH | Spectral/colour play; bus/device power qualification |
| `S034` | LTR390 UV/light | RESEARCH | UV/ambient story, not an uncalibrated health/UV safety instrument |
| `S035` | Four quadrant light seeker | EXPANSION | Four optical pickups + extra channels and mount; no head servo allocated |
| `S036` | BME280 temperature/humidity/pressure | EXPANSION | I2C 0x76/0x77 check vs BerryIMU pressure sensor |
| `S037` | BMP280 pressure only | OPTIONAL STOCK | Photographed owned; not humidity, not motion |
| `S038` | SHT4x/SHT41 fog the glass | EXPANSION | I2C 0x44 typical, mounted breath aperture, humidity response/condensation protection |
| `S039` | DS18B20 waterproof probe | EXPANSION | Tea Buddy/aquarium, isolated sealed waterproof probe and electrical safety |
| `S040` | MLX90614 noncontact temperature | EXPANSION | Thermal reading at distance, no health diagnosis |
| `S041` | MLX90640 thermal camera | RESEARCH | Power/processing budget and privacy; thermal silhouettes not identities |
| `S042` | AMG8833 Grid-EYE thermal array | RESEARCH | Alternative thermal matrix, frame rate/FOV limitations |
| `S043` | SCD40 real CO2 | EXPANSION | Physical airflow and warm-up; not inferred from equivalent VOC |
| `S044` | SGP30 VOC | EXPANSION | Air-quality game, baseline/calibration and ventilation |
| `S045` | BME688 gas/environment | EXPANSION | Gas signatures not medical/food safety diagnosis |
| `S046` | ENS160 air quality | EXPANSION | Alternative gas sensor, offset and humidity compensation |
| `S047` | PM2.5 SPS30/PMS5003 | RESEARCH | Bulky fan/air path, power/noise conflict with mini enclosure |
| `S048` | MAX9814 analog mic | OWNED SPARE | Not a speaker amplifier; Sense already includes PDM mic |
| `S049` | Sound event classifier on existing mic | REQUIRED CAPABILITY / OPTIONAL SOUNDS | Post-AEC, clap/whistle/speech/noise events and false positives; no directional inference |
| `S050` | Second mic for direction | EXPANSION | Requires phase/mic geometry, pins/audio reference; one PDM mic cannot localize voice |
| `S051` | Acoustic sonar with speaker/mic | RESEARCH | Echo/range precision not assumed; conflicts with own TTS and acoustic ecology |
| `S052` | VL53L5CX multizone ToF | RESEARCH | More processing/power; not simple replacement for floor coverage |
| `S053` | HuskyLens AI camera | RESEARCH | Duplicate camera hardware unless measurable benefit; price/power/fit |
| `S054` | INA219 current monitor | EXPANSION | Battery/servo sensing; calibrated shunt, rails, rates, not direct force |
| `S055` | HX711 load cell | EXPANSION | Mountable scale/stress game; actual strain gauge required |
| `S056` | GSR / EDA | SENSITIVE OPT-IN | Contact measurement consent/electrical isolation; no mental state diagnosis |
| `S057` | Conductive stretch cord | RESEARCH | Tail/belly position sensing, ADC and repeatability |
| `S058` | IR break-beam pair | EXPANSION | Coin-slot mouth/feed game, aperture and false beam handling |
| `S059` | IR reflective obstacle | OWNED SPARE | Not a replacement for physically qualified cliff ToFs |
| `S060` | VS1838B IR receiver | EXPANSION | Remote game/commands, no bypass of operator motion permissions |
| `S061` | Spill/wet feet detection | RESEARCH | Safe nonmains contact circuit and corrosion, battery water safety |
| `S062` | Capacitive soil moisture | RESEARCH | Plant-buddy external pod, weather protection |
| `S063` | AS3935 lightning | RESEARCH | Ambient environmental demo; no safety guarantee |
| `S064` | 433MHz RXB6 receiver | SENSITIVE OPT-IN | Legal and privacy concerns, no covert device interception |
| `S065` | Loose mains ghost sense antenna | REJECTED FOR SAFETY | Do not add unprotected mains-coupled antenna or expose accidental voltage |
| `S066` | Geiger counter module | RESEARCH WITH SAFETY REVIEW | High-voltage modules may exist; no unreviewed onboard radioactive/high-voltage experiment |
| `S067` | Weather pod/window sensor | EXPANSION | Explicit remote optional enclosure, not required core footprint |
| `S068` | Coin slot mouth | EXPANSION | Physical break-beam game and separate object geometry, not substitution for key/candy grip |
| `S069` | Magnetic Tic-Tac-Toe Hall grid | EXPANSION | Many inputs or scanned matrix, removable game board |
| `S070` | Four-direction sound/LED system | RESEARCH | Needs more sources/sensors, not a single mic's bearing |
| `S071` | Self-test beep, battery, touch and floor | REQUIRED OBSERVABILITY | Health from measured freshness, faults and explicit source |
| `S072` | Bluetooth phone presence | OPT-IN VIRTUAL SENSE | Signal strength not exact proximity/bearing; user consent |
| `S073` | MCP desktop app activity | OPT-IN VIRTUAL SENSE | AI agent/coding session, reminders and weather with explicit scope and privacy |
| `S074` | ESP-NOW satellite sensors | RESEARCH | Not required for Mac group; radio channel/messaging/security must be qualified |
| `S075` | Environmental audio/music tempo | EXPANSION | Use same mic and speaker processing without extra hardware; do not play copyrighted tracks |

## D. Pet toys, personality modes, games and cosmetic additions

| ID | Idea or requirement | Design status | Day-zero reservation, constraint, or proof required |
| --- | --- | --- | --- |
| `G001` | Blink, gaze, 20-expression face and sleepy rest | REQUIRED | OLED face engine; responsive offline eyes and context changes |
| `G002` | Emotion Lab and sensor-to-emotion simulator | REFERENCE | Retain playful mapping, reject unsafe blind retreat and false directional hearing |
| `G003` | Tamagotchi decaying needs | EXPANSION SOFTWARE | Simulated drives with user opt-out/quiet priority |
| `G004` | Memory and spontaneous callbacks | REQUIRED | Truthful per-robot experiences remembered across sessions |
| `G005` | Dreams and next-day storytelling | EXPANSION SOFTWARE | Clearly fictional dreams vs real observed event |
| `G006` | Evolving invented language | EXPANSION SOFTWARE | Peer game with opt-in, never obscure stop commands |
| `G007` | One speaker, six voices/characters | EXPANSION SOFTWARE | Style/personality demo, distinct robot identity remains canonical |
| `G008` | Secret life and Easter eggs | EXPANSION SOFTWARE | Quiet, consent and nonintrusive schedule |
| `G009` | Desk RPG over weeks | EXPANSION SOFTWARE | Saved game state and bounded peer/user turns |
| `G010` | Pomodoro focus buddy, alarm and clock | EXPANSION SOFTWARE | Opt-in timers and true Mac wall time, reminders |
| `G011` | Home Assistant and MCP household control | OPT-IN EXPANSION | Tool credentials isolated; no unsafe robotic arm authority |
| `G012` | PC assistant / desktop activity pet | OPT-IN EXPANSION | User-selected AI job/coding status, clear privacy |
| `G013` | Claude Desktop Buddy / HachimoDock / Tokpet patterns | RESEARCH | Agent task state mapped to emotions without scraping private work |
| `G014` | Music sync, dance and choreography | EXPANSION SOFTWARE | Recorded safe clips, servo/stepper envelope and permission |
| `G015` | Teach-a-move / pose-to-teach | EXPANSION HARDWARE | Need servo positional feedback or external encoder; don't infer from PWM target |
| `G016` | RPS game, mimic/peekaboo, speed tap | EXPANSION SOFTWARE | Camera/touch confidence and cooldown |
| `G017` | Magnetic snacks and cube games | EXPANSION HARDWARE | Hall/NFC/physical tokens, not a replacement for keys/candy acceptance |
| `G018` | Magnetic hats changing personality | RESERVE NOW | Costume clips and optional reed/Hall identity sensor |
| `G019` | Wagging tail and moving ears | EXPANSION | Need extra actuator, pin, current and mounting; initial two servos are lift and grip |
| `G020` | Pet purr/sound effects | EXPANSION SOFTWARE | Short original/public-domain sounds, speaker arbitration and quiet mode |
| `G021` | Diffused glowing chest heart | RESERVE NOW | One RGB pixel or LED, voltage/logic/standby and notifications |
| `G022` | Squeezable belly | EXPANSION | FSR or contact sensor with printed belly insert |
| `G023` | Twistable nose dial | EXPANSION | AS5600/magnetic encoder or potentiometer, accessible case |
| `G024` | Wobbly antenna | RESERVE NOW | Static safe removable flexible cosmetic, optional input if proven |
| `G025` | Thought bubble rear/e-ink second display | EXPANSION | Separate module, high pin/space cost and rear visibility |
| `G026` | Servo pan/tilt head | EXPANSION HARDWARE VARIANT | Not in two servo allocation; requires third/fourth actuator and confirmed new center of mass |
| `G027` | 4-servo body language / dance | EXPANSION HARDWARE VARIANT | Cannot be "free" on two-servo lift+grip base |
| `G028` | Two pets and five pet interaction | REQUIRED | Digital messages and individual characters; coordinated games |
| `G029` | Self dock / go home | EXPANSION HARDWARE | AprilTag, charger contacts, path safety, alignment verification |
| `G030` | Remote phone and ESP-NOW control | EXPANSION | Operator-only control path, no motion permission from broadcasts |
| `G031` | Camera see-what-it-sees and AI Eye | REQUIRED | Real fresh image to VLM; scene comments are validated before claims |
| `G032` | Hand/face mimic and personalized gestures | EXPANSION | Do not infer face identity without opt-in data and evaluation |
| `G033` | PIR homecoming and attentive greeting | EXPANSION | Presence source with evidence/cooldown and no generic repeated speech |
| `G034` | Breath fog / tea / aquarium / plant/weather modes | EXPANSION | Physical external sensors/safety and signed readings |
| `G035` | PC agent mirrors and AI coding emotions | EXPANSION SOFTWARE | MCP/status protocols, not scraping or broad credentials |
| `G036` | Dog bark on understanding / playful language | EXPANSION | Dogo pet pattern, sounds prioritized below humans |
| `G037` | Educational games and board game magnets | EXPANSION | Real interactive props and physical scene analysis |
| `G038` | Expression costumes / custom avatar / GIF | EXPANSION SOFTWARE | SSD1306 monochrome limits; no false color/60fps promise |
| `G039` | Peer physical chasing/handoff | RESEARCH HARDWARE | Not within one-front-ToF collision coverage; separate multi-robot safety program |
| `G040` | Social games with robot-robot rivalry | REQUIRED EXPERIENCE | Can be stationary with expressive peer turns before physical group roaming |
| `G041` | Household sounds and custom whistle | EXPANSION SOFTWARE | Post AEC, false positives, no implied sound bearing |
| `G042` | Mood from ambient illumination/temperature | EXPANSION | Real sensor required; simulated mood not a weather instrument |
| `G043` | Handling/lap/cuddle/gentle squeeze | REQUIRED + EXPANSION | IMU/touch required; FSR/piezo optional, immediate motion inhibition |
| `G044` | Self-perception and confidence | REQUIRED | Actual sensor checks, no fabricated emotional states |
| `G045` | Pet remembers user and spontaneous stories | REQUIRED | Truthful per-robot memory provenance and consent |
| `G046` | Multi-robot peer fun with distinct culture | REQUIRED EXPERIENCE | Five identical core units but evolving individual character histories |

## E. Historical research and new-find queues retained, not silently implemented

| ID | Idea or requirement | Design status | Day-zero reservation, constraint, or proof required |
| --- | --- | --- | --- |
| `H001` | Historical section 17: Xiaozhi First, Emotion Lab, old 3 forks | REFERENCE | Earlier Xiaozhi packs retained; not substitute for current Sense/WROOM platform |
| `H002` | Historical section 18: Xiaozhi mod packs and six week schedule | REFERENCE | Touch/motion/cliff/dance ideas mapped here; old two-TCRT5000 scheme not accepted edge coverage |
| `H003` | Historical section 19: sensor leaderboard and waves | PRESERVE | Every named sensor family appears in group C, with source/fit/safety flags |
| `H004` | Historical section 20: sensors/emotions/24 idea shortlist | PRESERVE | Mapped to groups B/C/D; no automatic reverse or single-mic voice direction |
| `H005` | Historical section 21: finds from Reddit/YouTube | PRESERVE | Source register includes original patterns; a video demo does not equal source license or code |
| `H006` | Historical section 22: newly found projects Nov 7 and Nov 9 | RESEARCH | Claude Desktop Buddy, Tiny Engineer, JARVIS, coding agent pet, Dogo, HachimoDock, Tokpet, Sesame Robot, MoodiMOS, Meta Muse, Tiny Touch DeskBuddy, Duckbert, AI Ball, AI DeskBuddy and others retained as leads |
| `H007` | Historical section 23: reference BOM and fork list | PRESERVE | StackChan, MyDeskRobo, AI Pet Robot V2, Sentio, Xiaozhi-Pet, Claude Desktop Buddy remain candidates, not verified source integrations |
| `H008` | Eilik/EMO/Cozmo/Vector/Mochi/Fetch comparisons | INSPIRATION | Character and appearance pattern, not copying closed commercial personality engines |
| `H009` | Projects with no confirmed source/license | REVIEW | Do not copy copyrighted binary, STL or code from partial videos simply because public URL exists |
| `H010` | New external sources and model/library claims | SOURCE CHECK | Verify per pinned release/license/readme/actual code; never turn user's unverified market/pricing/model benchmark into repo truth |

## Explicit status preservation for historically conflicting details

The original HTML's GPIO41/42 MAX30102 wiring, auto-reverse upon cliff, unsafe fault-degraded retreat, proposed relaxed audio A2 gate, 700 half-steps/s treated as implemented, `CAMERA_GRAB_LATEST` treated as proven, current RoboEyes integration, 40ms five-sensor scan, invented STT/TTS contention results, unmeasured 1.85A peaks, misleading $38.44 basket and $34 IP5306 selection are **not final instructions**. Preserve them as research in the original artifact. Refer to [engineering audit](../research/2026-11-09-html-verification.md) and [full gate](decisions-before-hardware.md) for safe resolutions.

## Requirement vs idea vs evidence

Every feature must eventually have `feature_id`, named origin or URL, code/physical owner, power/pins/location, licensed upstream SHA, chosen software adapter, permission/data sensitivity, declared cost, acceptance test, `not_attempted | source_reviewed | simulated | software_passed | bench_passed | accepted` state, and evidence link. This register does **not** mark feature delivery. Add new user research ideas as new IDs, never erase previous IDs; mark superseded and link the successor. Safety-related `REJECTED` items remain visible in history to prevent reintroduction.

A full URL list from the uploaded HTML was not embedded in this Markdown file; its live HTML has many repeated/unique links, some in historical sections. The curated and previously inspected official links live in [source map](../source-map.md) and [reuse register](reuse-register.md). Do not claim every external URL was visited or every creator video was watched just because its idea is traceable here.
