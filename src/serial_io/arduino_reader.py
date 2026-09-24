"""Threaded PySerial reader for Arduino packets with auto-reconnect.

Features 8/64: if the serial port fails to open, is unplugged, or stops
delivering data, the reader keeps retrying with a short backoff until the app
stops it. The UI is notified via `state_changed` ("reconnecting") and
`error_received` (one message per failed attempt).
"""
from __future__ import annotations

import threading
import time
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except Exception:  # pragma: no cover - import error shown in UI
    serial = None
    list_ports = None

from PySide6.QtCore import QObject, Signal

from src.config import RECONNECT_RETRY_S, SERIAL_BAUD, SERIAL_TIMEOUT_S, STALE_DATA_TIMEOUT_S
from src.data_models import SensorSample
from src.serial_io.packet_parser import PacketParseError, PacketParser


class _SerialStaleError(Exception):
    """Raised when no data arrives for longer than the stale timeout."""


class ArduinoReader(QObject):
    sample_received = Signal(object)  # SensorSample
    error_received = Signal(str)
    state_changed = Signal(str)

    def __init__(self, port: str, baud: int = SERIAL_BAUD, require_crc: bool = True, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self.require_crc = require_crc
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._serial = None
        self.parser = PacketParser(require_crc=require_crc)

    @staticmethod
    def available_ports() -> list[str]:
        if list_ports is None:
            return []
        return [p.device for p in list_ports.comports()]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self.state_changed.emit("stopped")

    def write_command(self, command: str) -> None:
        if self._serial is None:
            return
        if not command.endswith("\n"):
            command += "\n"
        try:
            self._serial.write(command.encode("ascii", errors="ignore"))
        except Exception as exc:
            self.error_received.emit(f"Serial write failed: {exc}")

    # --------------------------------------------------------------- loop
    def _run(self) -> None:
        if serial is None:
            self.error_received.emit("pyserial is not installed")
            return
        while not self._stop.is_set():
            try:
                self._serial = serial.Serial(self.port, self.baud, timeout=SERIAL_TIMEOUT_S)
                time.sleep(1.8)  # UNO reset after serial open
                self.state_changed.emit(f"connected:{self.port}")
                self._read_loop()
            except _SerialStaleError:
                self.error_received.emit(f"Serial link to {self.port} went silent; reconnecting...")
            except Exception as exc:
                self.error_received.emit(f"Serial connection problem on {self.port}: {exc}")
            finally:
                try:
                    if self._serial is not None:
                        self._serial.close()
                except Exception:
                    pass
                self._serial = None
            if self._stop.is_set():
                break
            self.state_changed.emit("reconnecting")
            # Backoff, cancellable.
            deadline = time.time() + RECONNECT_RETRY_S
            while time.time() < deadline and not self._stop.is_set():
                time.sleep(0.1)
        self.state_changed.emit("stopped")

    def _read_loop(self) -> None:
        assert self._serial is not None
        last_data = time.time()
        while not self._stop.is_set():
            try:
                line = self._serial.readline().decode("ascii", errors="replace").strip()
                if not line:
                    if time.time() - last_data > STALE_DATA_TIMEOUT_S:
                        raise _SerialStaleError()
                    continue
                sample: SensorSample = self.parser.parse(line)
                last_data = time.time()
                self.sample_received.emit(sample)
            except PacketParseError as exc:
                self.error_received.emit(f"Packet parse error: {exc}")
            except Exception as exc:
                if isinstance(exc, _SerialStaleError):
                    raise
                self.error_received.emit(f"Serial read error: {exc}")
                raise
