"""Wialon Retranslator binary protocol (used by Wialon and other platforms to forward units)."""

from __future__ import annotations

import struct

from ..records import Mapping, apply_sensors, clean, params_to_counters


class RetranslatorSession:
    proto = "wialon_retranslator"

    def __init__(self, mapping: Mapping | None = None):
        self.buf = b""
        self.ext_id: str | None = None
        self.mapping = mapping or Mapping()

    def feed(self, data: bytes) -> list[tuple[list[dict], bytes]]:
        self.buf += data
        out = []
        while len(self.buf) >= 4:
            total = 4 + struct.unpack_from("<I", self.buf, 0)[0]
            if total > 1_000_000:
                raise ValueError("retranslator packet too large")
            if len(self.buf) < total:
                break
            pkt, self.buf = self.buf[:total], self.buf[total:]
            rec = self.parse(pkt)
            out.append(([rec] if rec else [], b"\x11"))
        return out

    def parse(self, pkt: bytes) -> dict | None:
        pos = 4
        nul = pkt.index(b"\x00", pos)
        self.ext_id = pkt[pos:nul].decode("ascii", "replace")
        pos = nul + 1
        t, _flags = struct.unpack_from(">II", pkt, pos)
        pos += 8
        rec: dict = {"t": t}
        params: dict = {}
        while pos + 6 <= len(pkt):
            _btype, blen = struct.unpack_from(">Hi", pkt, pos)
            pos += 6
            end = pos + blen
            dtype = pkt[pos + 1]
            pos += 2
            nul = pkt.index(b"\x00", pos)
            name = pkt[pos:nul].decode("ascii", "replace")
            pos = nul + 1
            if name == "posinfo":
                lon, lat, alt = struct.unpack_from("<ddd", pkt, pos)
                spd, crs = struct.unpack_from(">hh", pkt, pos + 24)
                sats = pkt[pos + 28]
                if lat or lon:
                    rec.update(lat=lat, lon=lon, alt=alt, speed_kmh=float(spd), course=float(crs), sats=sats)
            elif dtype == 1:
                params[name] = pkt[pos : pkt.index(b"\x00", pos)].decode("utf-8", "replace")
            elif dtype == 3:
                params[name] = struct.unpack_from(">i", pkt, pos)[0]
            elif dtype == 4:
                params[name] = struct.unpack_from("<d", pkt, pos)[0]
            elif dtype == 5:
                params[name] = struct.unpack_from(">q", pkt, pos)[0]
            pos = end
        if isinstance(params.get("hdop"), (int, float)):
            rec["hdop"] = params["hdop"]
        params_to_counters(params, self.mapping, rec)
        apply_sensors(self.mapping, rec, params=params)
        return clean(rec)
