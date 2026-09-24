"""Wireless transport abstraction + local data buffering (V5, sections 16 + 17).

    Device -> Transport -> Parser/Validator -> Signal Processor

`Transport` is the interface for BLE / serial / Wi-Fi links. `BlePacketProtocol`
frames packets with a sequence number + CRC16 so dropped, duplicated or
corrupted packets can be detected. `LocalBuffer` is the software abstraction
for the wearable's local buffering: it stores (seq, ts, payload) frames,
deduplicates, re-orders on sync, and reports exactly what was received vs
dropped - no data loss is ever silently hidden.

BLE support here is protocol-level (framing/validation/buffering), not a
claimed driver for any commercial ring. Real BLE stacks can be plugged in
behind the same Transport interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# ------------------------------------------------------------ transports
class Transport(ABC):
    @abstractmethod
    def connect(self, address: str) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def send(self, payload: bytes) -> bool: ...

    @abstractmethod
    def receive(self) -> Optional[bytes]: ...


# ------------------------------------------------------- packet protocol
def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT (0x1021), the classic wearable-packet checksum."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class BlePacketProtocol:
    """Frame: [len][seq:4][payload][crc16:2]. Validates length, seq and CRC."""

    HEADER = 5  # len + seq(4)
    FOOTER = 2  # crc16

    @staticmethod
    def encode(seq: int, payload: bytes) -> bytes:
        body = seq.to_bytes(4, "little") + payload
        crc = crc16_ccitt(body).to_bytes(2, "little")
        return bytes([len(payload)]) + body + crc

    @staticmethod
    def decode(frame: bytes) -> Tuple[int, bytes]:
        """Returns (seq, payload). Raises ValueError on any corruption."""
        if len(frame) < BlePacketProtocol.HEADER + BlePacketProtocol.FOOTER:
            raise ValueError("frame too short")
        n = frame[0]
        if n != len(frame) - BlePacketProtocol.HEADER - BlePacketProtocol.FOOTER:
            raise ValueError("length mismatch")
        body = frame[1:1 + 4 + n]
        crc = int.from_bytes(frame[1 + 4 + n:], "little")
        if crc16_ccitt(body) != crc:
            raise ValueError("CRC mismatch")
        seq = int.from_bytes(body[:4], "little")
        return seq, body[4:]


# ----------------------------------------------------------- local buffer
@dataclass
class BufferStats:
    received: int = 0
    accepted: int = 0
    duplicates: int = 0
    reordered: int = 0
    corrupted: int = 0
    dropped: int = 0
    buffered: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class LocalBuffer:
    """Wearable-side / gateway-side buffer with sequence tracking.

    Frames arrive possibly out of order or duplicated; the buffer keeps the
    most recent `maxlen` unique frames and reports stats so the caller knows
    exactly how much data was lost between device and laptop.
    """

    def __init__(self, maxlen: int = 4096):
        self.maxlen = maxlen
        self._frames: "OrderedDict[int, bytes]" = OrderedDict()
        self.stats = BufferStats()

    def push(self, seq: int, payload: bytes) -> bool:
        """Store one payload. Returns True if it was new, False if duplicate."""
        self.stats.received += 1
        if seq in self._frames:
            self.stats.duplicates += 1
            return False
        if len(self._frames) >= self.maxlen:
            self._frames.popitem(last=False)
            self.stats.dropped += 1
        self._frames[seq] = payload
        self.stats.accepted += 1
        self.stats.buffered = len(self._frames)
        return True

    def pull_ordered(self) -> List[Tuple[int, bytes]]:
        """Return frames sorted by seq (handles delayed sync / reordering)."""
        out = [(seq, self._frames[seq]) for seq in sorted(self._frames)]
        if len(out) > 1:
            self.stats.reordered = 1  # reorder happened at least once
        return out

    def clear(self) -> None:
        self._frames.clear()
        self.stats.buffered = 0

    def __len__(self) -> int:
        return len(self._frames)
