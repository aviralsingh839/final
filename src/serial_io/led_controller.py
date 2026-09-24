"""LED/buzzer command helper."""
from __future__ import annotations


class LEDController:
    def __init__(self, writer=None):
        self.writer = writer
        self.last_state = None

    def set_writer(self, writer) -> None:
        self.writer = writer

    def send(self, command: str) -> None:
        if self.writer is None:
            return
        try:
            self.writer(command)
        except Exception:
            pass

    def set_risk_state(self, risk_percent: float, confidence: float = 100.0) -> None:
        if confidence < 35:
            state = "Y"
        elif risk_percent < 25:
            state = "G"
        elif risk_percent < 75:
            state = "Y"
        else:
            state = "R"
        if state != self.last_state:
            self.send(f"LED,{state}")
            self.last_state = state

    def beep(self) -> None:
        self.send("BEEP")
