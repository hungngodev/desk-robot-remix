"""One bounded WROOM bench command over USB serial. Never flashes a board."""

import argparse
import time

import serial
from desk_robot.transport import expected_ack, validate_command


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True, help="Exact USB serial port for the WROOM board")
    p.add_argument("--command", required=True, help='First test: "grip 95" (horn removed)')
    args = p.parse_args()
    op = validate_command(args.command)
    if op not in {"drive", "lift", "grip", "stop", "disarm"}:
        p.error("Choose one bounded drive/lift/grip, stop, or explicit disarm")
    with serial.Serial(args.port, 115200, timeout=0.03, write_timeout=0.15) as port:
        # Opening USB may reset the dev board. It remains disarmed through boot.
        time.sleep(2)
        port.reset_input_buffer()

        def transact(command):
            port.write((command + "\n").encode("ascii"))
            deadline = time.monotonic() + 0.35
            while time.monotonic() < deadline:
                line = port.readline(384).decode("ascii", errors="strict").strip()
                if line == expected_ack(command):
                    return
                if line.startswith("ERR "):
                    raise RuntimeError(line)
            raise TimeoutError("Uncertain ACK; movement will not be retried")

        if op in {"stop", "disarm"}:
            transact(args.command)
            print("Acknowledged " + op)
            return
        try:
            transact("arm")
            transact(args.command)
            duration = int(args.command.split()[3]) / 1000 + 0.05 if op == "drive" else 1.5
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                transact("keepalive")
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        finally:
            transact("stop")
        print("Job ended; stop acknowledged. Servo angle is commanded, not measured.")


if __name__ == "__main__":
    main()
