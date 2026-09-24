"""Checksums of the supported protocols (pinned by catalogue values and real device packets in tests)."""


def _crc16_reflected(data: bytes, poly: int, init: int) -> int:
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
    return crc & 0xFFFF


def crc16_arc(data: bytes) -> int:
    """Wialon IPS 2.x."""
    return _crc16_reflected(data, 0xA001, 0x0000)


def crc16_modbus(data: bytes) -> int:
    """Galileosky."""
    return _crc16_reflected(data, 0xA001, 0xFFFF)


def crc16_ccitt(data: bytes) -> int:
    """EGTS frame data (CRC-16/CCITT-FALSE)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def crc8_egts(data: bytes) -> int:
    """EGTS transport header."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) if crc & 0x80 else crc << 1
            crc &= 0xFF
    return crc
