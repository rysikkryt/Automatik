import can

from sim import j1939
from sim.canbus import replay

WORKING_HOURS_UTC = 1789455600  # 2026-09-15 07:00 UTC = 10:00 MSK, inside the day shift


def test_ecu_emulator_broadcasts_and_answers_requests(tmp_path):
    trace = tmp_path / "harvester.asc"
    with can.Bus(interface="virtual", channel="itles-test") as ecu, can.Bus(interface="virtual", channel="itles-test") as tracker:
        identifier, data = j1939.request_frame(65253, 0xF9, destination=0x00)
        tracker.send(can.Message(arbitration_id=identifier, data=data, is_extended_id=True))
        stats = replay("harvester", WORKING_HOURS_UTC, 30, ecu, seed=3, log_path=str(trace))
        received = []
        while (msg := tracker.recv(timeout=0)) is not None:
            received.append(msg)
    assert stats["requests_answered"] == 1
    decoded = [j1939.decode_frame(m.arbitration_id, bytes(m.data)) for m in received]
    hours = [d[2][247].value for d in decoded if d and d[0] == 65253]
    # Harvester ECU answers only the request; 30 s is below the 0.05 h step, so the start value.
    assert hours == [3000.0]
    assert any(d and d[0] == 61444 for d in decoded)
    frames = list(can.ASCReader(str(trace)))
    assert len(frames) == stats["frames_sent"]
