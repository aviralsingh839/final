"""Experimental VoxVasc tab."""
from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QGroupBox, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from src.models.voice_vasc_model import VoiceVascEstimator, wav_features


class VoiceVascTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.estimator = VoiceVascEstimator()
        self.live_pitch = None
        self.live_score = 0.0
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        title = QLabel("VoxVasc Experimental Voice Module")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        warning = QLabel(
            "This is experimental. Voice features do not measure testosterone or diagnose PCOS. "
            "Use this only as a low-weight educational proxy."
        )
        warning.setObjectName("WarningText"); warning.setWordWrap(True); root.addWidget(warning)
        box = QGroupBox("Live MAX4466 / WAV analysis")
        bl = QVBoxLayout(box)
        self.live_label = QLabel("Live pitch: -- Hz | VoxVasc score: --")
        self.live_label.setObjectName("StatValue")
        load_btn = QPushButton("Load sustained-vowel WAV file")
        load_btn.clicked.connect(self.load_wav)
        self.report = QTextEdit(); self.report.setReadOnly(True)
        self.report.setText(
            "Best voice protocol:\n"
            "1. Record a sustained vowel 'aaa' for 3 seconds in a quiet room.\n"
            "2. Keep same microphone distance for all volunteers.\n"
            "3. Use the result only as an experimental add-on; final risk is dominated by metabolic, sleep, stress and circadian data."
        )
        bl.addWidget(self.live_label); bl.addWidget(load_btn); bl.addWidget(self.report)
        root.addWidget(box)

    def update_live(self, pitch_hz: float | None, mic_rms: float | None):
        score, note = self.estimator.score(pitch_hz, mic_rms)
        self.live_score = score
        if pitch_hz and pitch_hz > 0:
            self.live_label.setText(f"Live pitch: {pitch_hz:.1f} Hz | VoxVasc score: {score:.0f}%")
        else:
            self.live_label.setText("Live pitch: -- Hz | VoxVasc score: disabled")

    def load_wav(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose WAV", "", "WAV files (*.wav)")
        if not path:
            return
        try:
            feat = wav_features(path)
            score, note = self.estimator.score(feat.get("pitch_hz"), feat.get("rms"))
            self.report.setText(
                f"File: {path}\n"
                f"Pitch: {feat.get('pitch_hz')} Hz\n"
                f"RMS: {feat.get('rms')}\n"
                f"VoxVasc score: {score:.0f}%\n\n"
                f"{note}\n\n"
                "Do not interpret this as measured androgen or a diagnostic feature."
            )
        except Exception as exc:
            self.report.setText(f"Could not analyze WAV: {exc}")
