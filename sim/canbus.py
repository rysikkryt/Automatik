"""ECU emulator on a python-can bus: broadcasts a simulated machine's J1939 traffic
and answers Request PGN 59904.

interface="virtual" runs in the sandbox; on the qualification bench the same code
drives a real USB-CAN adapter (socketcan, pcan, slcan, kvaser, ...) wired to the
tracker's CAN input, so the tracker sees the frames it would see on a machine.
"""

from __future__ import annotations

import argparse
import time

import can

from .machine import PROFILES, Machine


def replay(profile_key: str, start_utc: int, seconds: int, bus: can.BusABC, seed: int = 1,
           realtime: bool = False, log_path: str | None = None) -> dict:
    machine = Machine(PROFILES[profile_key], seed, start_utc, days=seconds // 86400 + 1)
    logger = can.Logger(log_path) if log_path else None  # format from extension: .asc, .blf, .log, .csv
    stats = {"frames_sent": 0, "requests_answered": 0}

    def send(identifier: int, data: bytes, t: float) -> None:
        msg = can.Message(arbitration_id=identifier, data=data, is_extended_id=True, timestamp=t)
        bus.send(msg)
        stats["frames_sent"] += 1
        if logger:
            logger.on_message_received(msg)

    for t in range(start_utc, start_utc + seconds):
        state = machine.step(t)
        while (incoming := bus.recv(timeout=0)) is not None:
            for identifier, data in machine.respond(incoming.arbitration_id, bytes(incoming.data), state):
                send(identifier, data, t)
                stats["requests_answered"] += 1
        for identifier, data in machine.can_frames(state):
            send(identifier, data, t)
        if realtime:
            time.sleep(1)
    if logger:
        logger.stop()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="harvester", choices=sorted(PROFILES))
    parser.add_argument("--interface", default="virtual")
    parser.add_argument("--channel", default="itles")
    parser.add_argument("--bitrate", type=int, default=250000)  # J1939 default
    parser.add_argument("--start", type=int, default=int(time.time()))
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--log", help="write a trace (.asc/.blf) for CAN tools")
    args = parser.parse_args()
    kwargs = {} if args.interface == "virtual" else {"bitrate": args.bitrate}
    with can.Bus(interface=args.interface, channel=args.channel, **kwargs) as bus:
        print(replay(args.profile, args.start, args.seconds, bus, realtime=args.realtime, log_path=args.log))


if __name__ == "__main__":
    main()
