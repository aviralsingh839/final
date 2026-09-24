"""Sensor diagnostics page (feature 59) plus logs and calibration history.

Shows per-sensor presence and status, the data-quality log, the error/fault
log, the calibration history, and the model registry, with a CSV export button.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.data_models import FeatureVector, SensorSample
from src.serial_io.packet_parser import decode_status_flags


def _fmt_ts(ts: float) -> str:
    import time

    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


class DiagnosticsPanel(QWidget):
    export_requested = Signal()

    SENSORS = [
        ("ppg", "MAX30102 PPG (IR)"),
        ("spo2", "SpO₂ estimate"),
        ("ecg", "AD8232 ECG"),
        ("temp0", "DS18B20 skin temp"),
        ("temp1", "DS18B20 second temp"),
        ("gsr", "GSR electrodes"),
        ("fsr", "FSR finger pressure"),
        ("imu", "MPU6050 motion"),
        ("lux", "BH1750 light"),
        ("env", "BME280 environment"),
        ("mic", "MAX4466 microphone"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)

        # Left column: sensor diagnostics + model registry.
        left = QVBoxLayout()
        sensors_box = QGroupBox("Sensor Diagnostics")
        grid = QGridLayout(sensors_box)
        self.sensor_labels: dict[str, QLabel] = {}
        for i, (key, name) in enumerate(self.SENSORS):
            grid.addWidget(QLabel(name), i, 0)
            value = QLabel("--")
            value.setObjectName("VitalValue")
            value.setStyleSheet("font-size: 12pt; font-weight: bold;")
            self.sensor_labels[key] = value
            grid.addWidget(value, i, 1)
        grid.addWidget(QLabel("Status bits"), len(self.SENSORS), 0)
        self.status_bits_label = QLabel("--")
        self.status_bits_label.setWordWrap(True)
        grid.addWidget(self.status_bits_label, len(self.SENSORS), 1)
        self.sensors_box = sensors_box
        left.addWidget(sensors_box)

        registry_box = QGroupBox("Model Registry (version tracking)")
        self.registry_text = QTextEdit()
        self.registry_text.setReadOnly(True)
        self.registry_text.setMaximumHeight(220)
        registry_box_layout = QVBoxLayout(registry_box)
        registry_box_layout.addWidget(self.registry_text)
        left.addWidget(registry_box)
        left.addStretch(1)
        outer.addLayout(left, 1)

        # Right column: logs + calibration history.
        right = QVBoxLayout()
        quality_box = QGroupBox("Data-Quality Log")
        self.quality_text = QTextEdit()
        self.quality_text.setReadOnly(True)
        qb = QVBoxLayout(quality_box)
        qb.addWidget(self.quality_text)
        right.addWidget(quality_box, 1)

        error_box = QGroupBox("Error / Fault Log")
        self.error_text = QTextEdit()
        self.error_text.setReadOnly(True)
        eb = QVBoxLayout(error_box)
        eb.addWidget(self.error_text)
        right.addWidget(error_box, 1)

        cal_box = QGroupBox("Calibration History")
        self.cal_text = QTextEdit()
        self.cal_text.setReadOnly(True)
        cb = QVBoxLayout(cal_box)
        cb.addWidget(self.cal_text)
        right.addWidget(cal_box, 1)

        export_btn = QPushButton("Export features to CSV")
        export_btn.clicked.connect(self.export_requested)
        right.addWidget(export_btn)
        outer.addLayout(right, 1)

    def set_registry(self, text: str) -> None:
        self.registry_text.setPlainText(text)

    def update_sensors(self, sample: Optional[SensorSample], fv: Optional[FeatureVector]) -> None:
        def set_label(key: str, text: str, ok: bool) -> None:
            label = self.sensor_labels.get(key)
            if label is None:
                return
            label.setText(text)
            from src.ui import theme as _theme
            label.setStyleSheet(f"font-size: 12pt; font-weight: bold; color: {_theme.GREEN if ok else _theme.RED};")

        if sample is None:
            for key in self.sensor_labels:
                self.sensor_labels[key].setText("--")
            return

        set_label("ppg", str(sample.ir), sample.ir > 0)
        spo2 = fv.spo2_pct if fv is not None else None
        set_label("spo2", f"{spo2:.1f}%" if spo2 is not None else "--", spo2 is not None)
        set_label("ecg", str(sample.ecg_raw) if sample.ecg_raw is not None and sample.ecg_raw >= 0 else "--",
                  sample.ecg_raw is not None and sample.ecg_raw >= 0)
        set_label("temp0", f"{sample.temp_c:.2f} °C" if math.isfinite(sample.temp_c) else "--", math.isfinite(sample.temp_c))
        set_label("temp1", f"{sample.temp1_c:.2f} °C" if sample.temp1_c is not None and math.isfinite(sample.temp1_c) else "--",
                  sample.temp1_c is not None and math.isfinite(sample.temp1_c))
        set_label("gsr", str(sample.gsr_raw), sample.gsr_raw > 0)
        set_label("fsr", str(sample.fsr_raw) if sample.fsr_raw is not None and sample.fsr_raw >= 0 else "--",
                  sample.fsr_raw is not None and sample.fsr_raw >= 0)
        set_label("imu", "OK" if math.isfinite(sample.ax_g) else "--", math.isfinite(sample.ax_g))
        set_label("lux", f"{sample.lux:.0f} lux" if sample.lux is not None and sample.lux >= 0 else "--",
                  sample.lux is not None and sample.lux >= 0)
        set_label("env", f"{sample.room_temp_c:.1f} °C" if sample.room_temp_c is not None and math.isfinite(sample.room_temp_c) else "--",
                  sample.room_temp_c is not None and math.isfinite(sample.room_temp_c))
        set_label("mic", f"rms {sample.mic_rms:.1f}" if sample.mic_rms else "--", bool(sample.mic_rms))

        flags = decode_status_flags(sample.status) if sample.status else []
        self.status_bits_label.setText(", ".join(flags) if flags else "no fault bits set")

    def set_quality_log(self, rows) -> None:
        lines = [f"[{_fmt_ts(r['ts'])}] {r['level'].upper()} | {r['metric']}: {r['message']}" for r in rows[:100]]
        self.quality_text.setPlainText("\n".join(lines) if lines else "No quality events yet.")

    def set_error_log(self, rows) -> None:
        lines = [f"[{_fmt_ts(r['ts'])}] {r['level'].upper()}: {r['message']}" for r in rows[:100]]
        self.error_text.setPlainText("\n".join(lines) if lines else "No errors logged.")

    def set_calibrations(self, rows) -> None:
        lines = []
        for r in rows:
            stats = r.get("stats_json", "")
            lines.append(f"[{_fmt_ts(r['ts'])}] duration {r['duration_s']:.0f}s, "
                         f"quality {r['quality']:.2f}, samples {r.get('samples', '')}\n  {stats[:160]}")
        self.cal_text.setPlainText("\n".join(lines) if lines else "No calibrations yet — press the baseline button or wait 5 minutes.")
