"""TCP network reader for the ESP8266 Wi-Fi bridge.

The ESP8266 bridge (arduino/chrono_pcos_esp8266_bridge) exposes a small TCP
server: the Arduino Mega serial packets are relayed to any connected TCP
client. This reader connects to that bridge and feeds the exact same packet
parser used for USB serial, with the same auto-reconnect behaviour.

Usage from the app:
    python -m src.app --net 192.168.4.1:7777
"""
from __future__ import annotations

import socket
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal

from src.config import RECONNECT_RETRY_S, WIFI_BRIDGE_DEFAULT_PORT
from src.serial_io.packet_parser import PacketParser


class NetworkReader(QObject):
    sample_received = Signal(object)  # SensorSample
    error_received = Signal(str)
    state_changed = Signal(str)

    def __init__(self, host: str, port: int = WIFI_BRIDGE_DEFAULT_PORT, require_crc: bool = True, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.require_crc = require_crc
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._sock: Optional[socket.socket] = None
        self.parser = PacketParser(require_crc=require_crc)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_socket()
        self.state_changed.emit("stopped")

    def write_command(self, command: str) -> None:
        if self._sock is None:
            return
        if not command.endswith("\n"):
            command += "\n"
        try:
            self._sock.sendall(command.encode("ascii", errors="ignore"))
        except Exception as exc:
            self.error_received.emit(f"Network write failed: {exc}")

    def _close_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._sock = socket.create_connection((self.host, self.port), timeout=3.0)
                self.state_changed.emit(f"connected:{self.host}:{self.port}")
                self._read_loop()
            except Exception as exc:
                self.error_received.emit(f"Wi-Fi bridge {self.host}:{self.port} unreachable: {exc}")
            finally:
                self._close_socket()
            if self._stop.is_set():
                break
            self.state_changed.emit("reconnecting")
            deadline = time.time() + RECONNECT_RETRY_S
            while time.time() < deadline and not self._stop.is_set():
                time.sleep(0.1)
        self.state_changed.emit("stopped")

    def _read_loop(self) -> None:
        assert self._sock is not None
        self._sock.settimeout(2.0)
        buffer = ""
        while not self._stop.is_set():
            try:
                chunk = self._sock.recv(4096).decode("ascii", errors="replace")
                if not chunk:
                    raise ConnectionError("bridge closed connection")
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sample = self.parser.parse(line)
                        self.sample_received.emit(sample)
                    except Exception as exc:
                        self.error_received.emit(f"Packet parse error: {exc}")
            except socket.timeout:
                continue
            except Exception as exc:
                self.error_received.emit(f"Network read error: {exc}")
                return  # back to _run: close socket, reconnect with backoff
