"""Checksums used by the tracker protocols.

Each variant is pinned by a catalogue check value in tests and, where available,
by packets captured from real devices (Traccar test vectors).
"""


def _crc16_reflected(data: bytes, poly: int, init: int) -> int:
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
    return crc & 0xFFFF


def crc16_arc(data: bytes) -> int:
    """CRC-16/ARC. Wialon IPS 2.0 (matches the official Gurtam examples)."""
    return _crc16_reflected(data, 0xA001, 0x0000)


def crc16_modbus(data: bytes) -> int:
    """CRC-16/MODBUS. Galileosky binary protocol."""
    return _crc16_reflected(data, 0xA001, 0xFFFF)


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF). EGTS service frame data."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def crc8_egts(data: bytes) -> int:
    """CRC-8 poly 0x31, init 0xFF, not reflected. EGTS transport header (HCS)."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) if crc & 0x80 else crc << 1
            crc &= 0xFF
    return crc
