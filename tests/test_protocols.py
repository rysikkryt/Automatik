import re
import struct

from sim.protocols import egts, galileosky, wialon_ips


def _record(i=0, **kw):
    base = dict(index=i, t=1789466400 + i * 30, lat=63.751234, lon=34.301234, valid=True, sats=11, speed_kmh=12.3,
                course=271.5, alt_m=120, hdop=0.9, inputs=1, power_mv=27900, gps_odometer_m=123456,
                rpm=1450.0, coolant_c=86, fuel_level_pct=62.4, fuel_total_raw=162469, can_b0_raw=None, engine_hours_x100=301790)
    base.update(kw)
    return galileosky.GalileoRecord(**base)


def test_galileosky_frames_round_trip():
    head = galileosky.head_packet("356307042441013")
    archive, records = galileosky.parse(head)
    assert not archive and records[0][0x03] == b"356307042441013"
    packets = galileosky.records_packets([_record(i) for i in range(40)], archive=True)
    assert all(len(p) <= galileosky.MAX_PACKET_BYTES for p in packets)
    parsed = [r for p in packets for r in galileosky.parse(p)[1]]
    assert len(parsed) == 40
    first = parsed[0]
    assert struct.unpack("<ii", first[0x30][1:]) == (63751234, 34301234)
    assert struct.unpack("<HH", first[0x33]) == (123, 2715)
    assert struct.unpack("<I", first[0xDB])[0] / 100 == 3017.9
    assert galileosky.expected_ack(packets[0]) == b"\x02" + packets[0][-2:]
    assert galileosky.parse(packets[0])[0] is True


def test_galileosky_parser_reads_real_packets_exactly(vectors):
    for h in vectors["galileosky_main"]:
        _, records = galileosky.parse(bytes.fromhex(h))
        assert records


def test_wialon_packets():
    login = wialon_ips.login("356307042441013", "secret")
    assert login.startswith(b"#L#2.0;356307042441013;secret;") and login.endswith(b"\r\n")
    assert wialon_ips.verify(login)
    m = wialon_ips.WialonMessage(1789466400, 55.743375, 37.661390, 12.4, 91.0, 150, 12, 0.9, 1,
                                 {"eng_hours": 3017.9, "ign": 1, "src": "can"})
    d = wialon_ips.data(m).decode()
    assert re.fullmatch(r"#D#150926;100000;5544\.60250;N;03739\.68340;E;12;91;150;12;0\.9;1;0;NA;NA;"
                        r"eng_hours:2:3017\.9,ign:1:1,src:3:can;[0-9A-F]{4}\r\n", d)
    assert wialon_ips.verify(d.encode())
    b = wialon_ips.blackbox([m, m])
    assert b.count(b"|") == 2 and wialon_ips.verify(b)


def test_egts_round_trip_includes_counters():
    p = egts.EgtsPoint(1789466400, 61.25, 46.65, True, 57.3, 300.0, 1234.5, 1, 120, 11, 0.9, True, False,
                       {1: 30179, 2: 2618345})
    packet = egts.transport(egts.teledata_records([p], 7), packet_id=42)
    decoded = egts.decode(packet)
    subs = {s["type"]: s for s in decoded["records"][0]["subrecords"] if s["type"] != "ABS_CNTR_DATA"}
    counters = [s for s in decoded["records"][0]["subrecords"] if s["type"] == "ABS_CNTR_DATA"]
    pos = subs["POS_DATA"]
    assert abs(pos["lat"] - 61.25) < 1e-6 and abs(pos["lon"] - 46.65) < 1e-6
    assert pos["course"] == 300 and pos["speed_kmh"] == 57.3 and pos["odometer_km"] == 1234.5
    assert {c["number"]: c["value"] for c in counters} == {1: 30179, 2: 2618345}


def test_egts_decoder_handles_real_packets(vectors):
    for h in vectors["egts"]:
        assert egts.decode(bytes.fromhex(h))["records"] is not None
