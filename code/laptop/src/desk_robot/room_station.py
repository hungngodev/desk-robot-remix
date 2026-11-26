"""One shared, opt-in USB room sensor feed, not a motor/speaker authority.

The Feather firmware is the only source of physical data. This decoder checks
framing, source identity, monotonic sample ages, counters and sensor units.
Every connection owns a fresh decoder epoch. USB serial is not cryptographic
device authentication and no observation can establish person identity.
"""
from __future__ import annotations

import asyncio
import json
import math
import secrets
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

from .soil_calibration import SoilCalibration

STATION = "room-pod-01"
ROOM_OBSERVATION_SOURCE = "local_usb_shared_station_observation_not_identity"
SENSORS = ("scd40", "bme688", "ld2410c", "soil", "amg8833")
MAX_FRAME_BYTES = 4096
# Per-port unpredictable causal marker. A delayed USB JSON frame written
# before this challenge must never inherit a fresh Mac receive timestamp.
USB_SYNC_TIMEOUT_S = 3.0
# The source of each report must postdate an ACK within this bounded window.
USB_POST_SYNC_FRAME_TIMEOUT_S = 2.5
UINT32 = 0xffffffff
# Mac receive time limits impossible station uptime advances on one USB epoch.
# 0.1% clock drift plus 3s scheduling slack; not a physical timing claim.
MAX_STATION_CLOCK_LEAD_S = 3.0
STATION_CLOCK_DRIFT_RATIO = 0.001
MAX_AGES_MS = {"scd40": 8500, "bme688": 3000, "ld2410c": 3000,
               "soil": 3000, "amg8833": 3000}


@dataclass(frozen=True)
class RoomObservation:
    seq: int
    at_ms: int
    received_at: float
    readings: dict
    summary: str
    # Explicitly separate from the per-pet camera or sensed-human memory.
    source: str = ROOM_OBSERVATION_SOURCE
    motion_authorized: bool = False
    charging_authorized: bool = False
    person_identified: bool = False
    # The USB frame station field is validated above; this is protocol
    # provenance, not cryptographic authentication of the attached Feather.
    station_id: str = STATION
    sensor_ages_ms: dict[str, int] | None = field(default=None, repr=False, compare=False)
    soil_calibration: SoilCalibration | None = field(default=None, repr=False, compare=False)


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate room station JSON property")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Nonfinite room JSON token {value}")


def _uint(value: object, *, zero: bool = True) -> int:
    if type(value) is not int or not (0 if zero else 1) <= value <= UINT32:
        raise ValueError("Room counter or sample timestamp is not a uint32")
    return value


def _number(value: object, low: float, high: float) -> float:
    if type(value) not in (float, int):
        raise ValueError("Invalid room sensor number")
    # Python may raise OverflowError while converting a large JSON integer
    # to float for isfinite(). A malformed USB sample is a rejected frame,
    # never a reason to tear down the station reader and reconnect.
    try:
        if not math.isfinite(value):
            raise ValueError("Invalid room sensor number")
    except OverflowError as exc:
        raise ValueError("Invalid room sensor number") from exc
    if not low <= value <= high:
        raise ValueError("Room sensor reading out of range")
    return float(value)


def _value(data: dict, field: str, low: float, high: float) -> float:
    if field not in data:
        raise ValueError(f"Missing room sensor field {field}")
    return _number(data[field], low, high)


def _boolean(data: dict, field: str) -> None:
    if type(data.get(field)) is not bool:
        raise ValueError(f"Invalid room sensor boolean {field}")


def _valid_reading(sensor: str, data: dict, clock: int) -> bool:
    if not isinstance(data, dict):
        raise ValueError("Invalid room sensor object")
    _boolean(data, "valid")
    if data["valid"] is False:
        if set(data) != {"valid"}:
            raise ValueError("Invalid sensor cannot claim measurements")
        return False
    timestamp = _uint(data.get("sample_ms"))
    age = (clock - timestamp) & UINT32
    if age > MAX_AGES_MS[sensor]:
        raise ValueError(f"Stale {sensor} physical sample")
    fields = {
        "scd40": {"co2_ppm", "temp_c", "humidity_pct"},
        "bme688": {"temp_c", "humidity_pct", "pressure_pa", "gas_ohms"},
        "ld2410c": {"presence", "stationary", "moving",
                    "stationary_cm", "moving_cm"},
        "soil": {"raw_adc"},
        "amg8833": {"pixels_c"},
    }[sensor]
    if set(data) != {"valid", "sample_ms"} | fields:
        raise ValueError(f"Unknown or missing {sensor} measurement field")
    if sensor == "scd40":
        _value(data, "co2_ppm", 1, 50000)
        if type(data["co2_ppm"]) is not int:
            raise ValueError("CO2 ppm must be an integer")
        _value(data, "temp_c", -40, 125)
        _value(data, "humidity_pct", 0, 100)
    elif sensor == "bme688":
        _value(data, "temp_c", -40, 125)
        _value(data, "humidity_pct", 0, 100)
        _value(data, "pressure_pa", 30000, 125000)
        # Pinned BME680 2.0.5 uses zero as the unstable heater sentinel.
        _value(data, "gas_ohms", 1, 1e9)
        if type(data["gas_ohms"]) is not int:
            raise ValueError("Gas resistance must be an integer")
    elif sensor == "ld2410c":
        for key in ("presence", "stationary", "moving"):
            _boolean(data, key)
        for key in ("stationary_cm", "moving_cm"):
            _value(data, key, 0, 65535)
            if type(data[key]) is not int:
                raise ValueError("Radar distance must be an integer")
        if (data["stationary"] or data["moving"]) and not data["presence"]:
            raise ValueError("Radar target contradicts absent presence")
        if ((data["stationary"] and data["stationary_cm"] == 0)
                or (data["moving"] and data["moving_cm"] == 0)):
            raise ValueError("Active radar target requires a positive distance")
    elif sensor == "soil":
        # Firmware publishes only a bounded 12-bit integer from three ADC
        # samples. Reject a saturated rail, bool or floating JSON number even
        # if no optional wet/dry calibration has been provided by the owner.
        raw = data.get("raw_adc")
        if type(raw) is not int or not 1 <= raw <= 4094:
            raise ValueError("Invalid or saturated raw soil ADC sample")
    else:
        pixels = data.get("pixels_c")
        if not isinstance(pixels, list) or len(pixels) != 64:
            raise ValueError("AMG8833 needs exactly 64 thermal values")
        # Match the AMG8833 high-gain 0..80 C object range confirmed by
        # Panasonic. Do not accept another sensor variant's thermal range.
        for pixel in pixels:
            _number(pixel, 0, 80)
    return True


def _summary(readings: dict, calibration: SoilCalibration | None = None) -> str:
    # No inference of humans, health, camera objects, VOC concentration,
    # physical permission or room-wide mapping from these raw samples.
    bits: list[str] = []
    scd = readings["scd40"]
    if scd["valid"]:
        bits.append(f"Station CO2 {scd['co2_ppm']} ppm")
    bme = readings["bme688"]
    if bme["valid"]:
        bits.append(f"Station air {bme['temp_c']:.1f} C, "
                    f"humidity {bme['humidity_pct']:.0f}%, "
                    f"raw gas resistance {bme['gas_ohms']:.0f} ohms")
    radar = readings["ld2410c"]
    if radar["valid"]:
        if radar["presence"]:
            # This is anonymous echo distance, never person detection.
            targets = []
            if radar["moving"]:
                targets.append(f"moving {radar['moving_cm']:.0f} cm")
            if radar["stationary"]:
                targets.append(f"stationary {radar['stationary_cm']:.0f} cm")
            detail = (", " + ", ".join(targets)) if targets else ""
            bits.append("Station radar detected an echo" + detail)
        else:
            bits.append("Station radar reported no echo")
    soil = readings["soil"]
    if soil["valid"]:
        bits.append(f"Station soil probe raw ADC {soil['raw_adc']}")
        if calibration is not None:
            relative = calibration.percentage(soil["raw_adc"])
            bits.append(f"Station relative soil moisture {relative}% from measured calibration")
    thermal = readings["amg8833"]
    if thermal["valid"]:
        # Summarize only the observed range, not a person, bearing or heat
        # source identity. Sensor orientation and emissivity are unqualified.
        pixels = thermal["pixels_c"]
        bits.append(f"Station thermal raw {min(pixels):.1f}..{max(pixels):.1f} C "
                    "(64 unclassified pixels)")
    if not bits:
        return "No fresh room station measurements"
    fresh_count = sum(readings[sensor]["valid"] for sensor in SENSORS)
    prefix = (f"Partial room profile ({fresh_count}/{len(SENSORS)} fresh sensors): "
              if fresh_count < len(SENSORS) else "")
    return (prefix + "; ".join(bits))[:400]


def fresh_room_summary(observation: RoomObservation, *, now: float) -> str | None:
    """Recompute shared station summary expiring each sensor per MAX_AGES_MS.

    Returns None once every validated sensor has exceeded its physical age bound
    (never letting a stale sensor piggyback on a newer packet's receive clock).
    Legacy synthetic RoomObservation fixtures without sensor_ages_ms retain
    their precomputed summary within the aggregate caller window.
    """
    if observation.sensor_ages_ms is None:
        return observation.summary
    elapsed_ms = round(1000 * (now - observation.received_at))
    if elapsed_ms < 0:
        return None
    filtered: dict[str, dict] = {}
    any_fresh = False
    for sensor in SENSORS:
        raw = observation.readings.get(sensor)
        if not isinstance(raw, dict) or not raw.get("valid"):
            filtered[sensor] = {"valid": False}
            continue
        age_at_receipt = observation.sensor_ages_ms.get(sensor)
        if age_at_receipt is None or age_at_receipt + elapsed_ms > MAX_AGES_MS[sensor]:
            filtered[sensor] = {"valid": False}
        else:
            filtered[sensor] = raw
            any_fresh = True
    if not any_fresh:
        return None
    return _summary(filtered, observation.soil_calibration)


class RoomStationDecoder:
    def __init__(self, soil_calibration: SoilCalibration | None = None) -> None:
        if soil_calibration is not None and not isinstance(soil_calibration, SoilCalibration):
            raise ValueError("Soil calibration must use validated measured endpoints")
        self._soil_calibration = soil_calibration
        self._last_seq: int | None = None
        self._last_ms: int | None = None
        self._station_elapsed_ms = 0
        self._last_sensor_elapsed_ms: dict[str, int] = {}
        self._last_sensor_readings: dict[str, dict] = {}
        self._last_sensor_receipts: dict[str, tuple[float, int]] = {}
        self._revoked_sensors: set[str] = set()
        self._first_received_at: float | None = None
        self._last_received_at: float | None = None

    def accept(self, line: bytes | str, *, now: float) -> RoomObservation:
        if type(now) not in (float, int):
            raise ValueError("Finite Mac receive clock is required")
        try:
            finite_now = math.isfinite(now)
        except OverflowError:
            finite_now = False
        if not finite_now:
            raise ValueError("Finite Mac receive clock is required")
        if isinstance(line, bytes):
            if len(line) > MAX_FRAME_BYTES:
                raise ValueError("Oversized room station USB frame")
            line = line.decode("utf-8", errors="strict")
        if not isinstance(line, str) or not 1 <= len(line.encode("utf-8")) <= MAX_FRAME_BYTES:
            raise ValueError("Invalid station USB line")
        try:
            payload = json.loads(line, object_pairs_hook=_pairs,
                                 parse_constant=_reject_constant)
        except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
            raise ValueError("Malformed room station JSON") from exc
        if not isinstance(payload, dict) or set(payload) != {
            "v", "station", "seq", "at_ms", "readings"
        }:
            raise ValueError("Unknown room frame or forbidden control fields")
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError("Unknown room station protocol version")
        if payload["station"] != STATION:
            raise ValueError("Foreign room station source")
        seq = _uint(payload["seq"])
        clock = _uint(payload["at_ms"])
        if (self._last_seq is not None
                and not 0 < (seq - self._last_seq) & UINT32 < 0x80000000):
            raise ValueError("Replayed or backwards room station sequence")
        if (self._last_ms is not None
                and not 0 < (clock - self._last_ms) & UINT32 < 0x80000000):
            raise ValueError("Replayed or backwards room station acquisition clock")
        # Accumulate validated forward intervals, including every uint32 wrap.
        # Subtracting the first raw millis value would reset the drift fence
        # after 49.7 days and admit impossible source time from a live USB epoch.
        step_ms = ((clock - self._last_ms) & UINT32
                   if self._last_ms is not None else 0)
        elapsed_ms = self._station_elapsed_ms + step_ms
        if self._first_received_at is not None:
            if float(now) < self._last_received_at:
                raise ValueError("Backwards Mac room station receipt time")
            station_elapsed_s = elapsed_ms / 1000.0
            mac_elapsed_s = float(now) - self._first_received_at
            if station_elapsed_s > (mac_elapsed_s *
                                    (1.0 + STATION_CLOCK_DRIFT_RATIO)
                                    + MAX_STATION_CLOCK_LEAD_S):
                raise ValueError("Room station acquisition clock jumped ahead of Mac")
        readings = payload["readings"]
        if not isinstance(readings, dict) or set(readings) != set(SENSORS):
            raise ValueError("Missing or forbidden room station sensors")
        # Map each bounded sample age onto the cumulative station timeline.
        # A fresh report may repeat a slow sensor's sample, but must never
        # replace a newer acquisition with an older one, even across wrap
        # or an intervening invalid reading. Stage all updates atomically.
        sensor_elapsed_ms = self._last_sensor_elapsed_ms.copy()
        sensor_readings = self._last_sensor_readings.copy()
        sensor_receipts = self._last_sensor_receipts.copy()
        revoked = self._revoked_sensors.copy()
        sensor_ages_ms: dict[str, int] = {}
        for sensor in SENSORS:
            reading = readings[sensor]
            if _valid_reading(sensor, reading, clock):
                age = (clock - reading["sample_ms"]) & UINT32
                acquired = elapsed_ms - age
                previous = sensor_elapsed_ms.get(sensor)
                if previous is not None and acquired < previous:
                    raise ValueError(f"Backwards {sensor} acquisition clock")
                if previous is not None and acquired == previous:
                    if reading != sensor_readings[sensor]:
                        raise ValueError(f"Contradictory {sensor} acquisition values")
                    # Explicit producer invalidation retires this conversion.
                    # Keep sibling observations but never resurrect the old one.
                    if sensor in revoked:
                        readings[sensor] = {"valid": False}
                        continue
                    # A cached conversion cannot become younger merely because
                    # the station clock lags the Mac receipt clock.
                    first_at, first_age = sensor_receipts[sensor]
                    elapsed = min((float(now) - first_at) * 1000, MAX_AGES_MS[sensor] + 1)
                    age = max(age, first_age + round(elapsed))
                else:
                    # Returned observations contain mutable dictionaries/lists.
                    # Keep a detached witness even if a consumer edits them.
                    revoked.discard(sensor)
                    sensor_readings[sensor] = deepcopy(reading)
                    sensor_receipts[sensor] = (float(now), age)
                sensor_elapsed_ms[sensor] = acquired
                if age > MAX_AGES_MS[sensor]:
                    readings[sensor] = {"valid": False}
                else:
                    sensor_ages_ms[sensor] = age
            else:
                revoked.add(sensor)
        # Invalid frames never mutate counter fences. A USB reconnect must
        # create a NEW decoder instance only after actual port reopening.
        if self._first_received_at is None:
            self._first_received_at = float(now)
        self._last_seq = seq
        self._last_ms = clock
        self._station_elapsed_ms = elapsed_ms
        self._last_sensor_elapsed_ms = sensor_elapsed_ms
        self._last_sensor_readings = sensor_readings
        self._last_sensor_receipts = sensor_receipts
        self._revoked_sensors = revoked
        self._last_received_at = float(now)
        return RoomObservation(
            seq, clock, float(now), readings,
            _summary(readings, self._soil_calibration),
            station_id=payload["station"],
            sensor_ages_ms=sensor_ages_ms,
            soil_calibration=self._soil_calibration,
        )


class RoomSerialFeed:
    """One opt-in serial consumer, never an additional Mac brain or speaker.

    Port opens/reconnects are the only decoder epoch reset. Failed or stale
    frames are omitted; no old sample can reappear as a new room observation.

    Callback contract: on_observation MUST return promptly, perform no slow
    I/O, and must not block on model inference, locks, UI or async futures.
    It runs synchronously in the owned serial reader thread. An arbitrary
    permanently blocked third-party callback cannot be cancelled safely by
    Python and prevents confirmation of worker shutdown. Production Runtime
    satisfies this contract through a short call_soon_threadsafe handoff and
    one coalesced latest-only event loop callback, not work in this thread.
    Alternate consumers must supply their own similarly bounded handoff.
    """
    def __init__(self, port: str, on_observation: Callable[[RoomObservation], None],
                 soil_calibration: SoilCalibration | None = None,
                 on_disconnect: Callable[[], None] | None = None):
        if not isinstance(port, str) or not port.startswith("/dev/"):
            raise ValueError("Room station requires an explicit local serial device")
        self.port = port
        self.on_observation = on_observation
        self.soil_calibration = soil_calibration
        self.on_disconnect = on_disconnect
        self.last_error: str | None = None
        self.received = 0
        self.rejected = 0  # Invalid USB frames only, not application failures
        self.callback_failures = 0

    def _read_port(self, running: Callable[[], bool]) -> None:
        import serial  # optional hardware-only pyserial package, no simulation
        # pySerial 3.5 POSIX advisory lock: avoid two cooperating readers
        # interleaving bytes on this sole local USB station transport.
        # Device access and user consent remain separately enforced.
        with serial.Serial(self.port, baudrate=115200, timeout=.25,
                           write_timeout=.25, exclusive=True) as port:
            # Reset at real connection opening, not after a callback failure.
            self.last_error = None
            if not running():
                return
            # The Feather accepts repeated SYNC challenges. Re-issue one
            # after each report to exclude stale USB frames after a stall.
            def request_sync() -> tuple[bytes, float]:
                nonce = secrets.token_hex(8).encode("ascii")
                # Retire any partial command left in the powered Feather
                # parser by an interrupted USB write. A stale ACK produced
                # by that delimiter still cannot match the fresh nonce.
                request = b"\nSYNC " + nonce + b"\n"
                if port.write(request) != len(request):
                    raise RuntimeError("Room station SYNC write incomplete")
                return (b"SYNC_ACK " + nonce + b"\n",
                        time.monotonic() + USB_SYNC_TIMEOUT_S)

            expected, deadline = request_sync()
            synchronized = False
            frame_deadline = 0.0
            decoder = RoomStationDecoder(soil_calibration=self.soil_calibration)
            discard_until_newline = False
            while running():
                now = time.monotonic()
                if not synchronized and now >= deadline:
                    raise RuntimeError("Room station post-connect SYNC unacknowledged")
                if synchronized and now >= frame_deadline:
                    expected, deadline = request_sync()
                    synchronized = False
                # pySerial readline() inherits RawIOBase's per-read timeout.
                # A steady byte trickle can hide the outer SYNC/stop deadline
                # until the size limit. read_until() adds a whole-line timeout.
                line = port.read_until(b"\n", size=MAX_FRAME_BYTES + 1)
                if not line:
                    continue
                if not running():
                    break
                now = time.monotonic()
                if not synchronized and now >= deadline:
                    # A read may return an exact nonce ACK after the timeout.
                    # Never turn that overdue response into fresh USB evidence.
                    raise RuntimeError("Room station post-connect SYNC unacknowledged")
                # Framing belongs to the connection, not the SYNC state.
                # A truncated line's suffix cannot acknowledge a new epoch.
                complete_line = line.endswith(b"\n")
                discard_frame = discard_until_newline or not complete_line
                if synchronized and not discard_until_newline and not complete_line:
                    self.rejected += 1
                discard_until_newline = not complete_line
                if synchronized and now >= frame_deadline:
                    # An old line may finish arriving after a USB stall.
                    # Discard it rather than assigning a new host timestamp.
                    expected, deadline = request_sync()
                    synchronized = False
                    continue
                if discard_frame:
                    continue
                if not synchronized:
                    # No valid JSON may pass until the current challenge is
                    # acknowledged. Stale ACKs and older buffered frames drop.
                    # Arduino Serial.println emits CRLF. Match either exact
                    # terminator while retaining the full unpredictable nonce.
                    if line == expected or line == expected[:-1] + b"\r\n":
                        synchronized = True
                        frame_deadline = now + USB_POST_SYNC_FRAME_TIMEOUT_S
                    continue
                try:
                    evidence = decoder.accept(line, now=time.monotonic())
                except ValueError:
                    self.rejected += 1
                    continue
                # A cancellation may arrive while the read is blocked. Never
                # deliver that completed read into a retired connection epoch.
                if not running():
                    break
                try:
                    self.on_observation(evidence)
                except Exception as exc:
                    # Application callback failure is not a USB disconnect.
                    # Keep the decoder replay fence and serial epoch intact.
                    self.last_error = f"Room observation callback failed: {type(exc).__name__}: {exc}"
                    self.callback_failures += 1
                else:
                    self.received += 1
                if running():
                    # Even a callback failure must not authorize the next
                    # sensor report without a fresh host/Feather causal ACK.
                    expected, deadline = request_sync()
                    synchronized = False

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            reader_stop = threading.Event()
            worker = asyncio.create_task(asyncio.to_thread(
                self._read_port,
                lambda reader_stop=reader_stop: not stop.is_set() and not reader_stop.is_set(),
            ))
            cancelled = False
            try:
                # Cancelling asyncio.to_thread does not stop its OS thread.
                # Keep ownership until the serial port is actually closed.
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        cancelled = True
                        reader_stop.set()
                if cancelled:
                    # Consume any simultaneous serial error before propagating
                    # cancellation; no old reader may survive into a restart.
                    try:
                        worker.result()
                    except Exception:
                        pass
                    raise asyncio.CancelledError
                worker.result()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # shield() can propagate a serial error during the join.
                # Once cancellation was observed, never restart the reader.
                if cancelled:
                    raise asyncio.CancelledError from exc
                self.last_error = type(exc).__name__
            finally:
                reader_stop.set()
                if callable(self.on_disconnect):
                    try:
                        self.on_disconnect()
                    except Exception:
                        pass
            if not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1.0)
                except TimeoutError:
                    pass
