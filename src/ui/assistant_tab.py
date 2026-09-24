"""AI Assistant tab: chat interface over the AssistantEngine.

Two modes (shown in the header):
  * Local grounded — fully offline, answers built from real computed values.
  * Local + LLM — when CHRONO_LLM_URL / CHRONO_LLM_MODEL are set, questions go
    to an OpenAI-compatible endpoint with a context snapshot; falls back to
    local mode on any error.

The chat remembers the conversation: after any answer you can say "why?",
"more", or "and sleep?" to continue on the same or another topic.
"""
from __future__ import annotations

import html as _html
import re as _re
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.config import UserProfile
from src.data_models import FeatureVector, RiskResult
from src.models.assistant import PROVIDERS, AssistantContext, AssistantEngine, LLMAssistant

QUICK_QUESTIONS = [
    "Why is my risk elevated?",
    "What is my heart rate?",
    "How did I sleep?",
    "Any anomalies?",
    "What should I do today?",
    "Compare today vs yesterday",
]


class _LLMWorker(QThread):
    """Runs the LLM call off the UI thread; emits '' on failure/None."""

    done = Signal(str)

    def __init__(self, engine: AssistantEngine, question: str, context_text: str):
        super().__init__()
        self._engine = engine
        self._question = question
        self._context = context_text

    def run(self):
        ans = self._engine.llm.chat(self._question, self._context)
        self.done.emit(ans or "")


def _rich(text: str) -> str:
    """Light markdown for chat bubbles: escape HTML, bold **...**, keep line breaks."""
    t = _html.escape(text)
    t = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t.replace("\n", "<br>")


class AISettingsDialog(QDialog):
    """Configure a free-tier / local LLM provider for conversational answers."""

    def __init__(self, engine: AssistantEngine, on_configured=None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.on_configured = on_configured
        self.setWindowTitle("AI assistant settings")
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        info = QLabel(
            "Connect a free-tier or local LLM to get conversational answers over the same "
            "real data. Groq, Google Gemini and OpenRouter offer free API tiers — create a "
            "free key at their site and paste it below (stored only in this project's "
            "data/ai_config.json). Ollama runs 100% locally with no key."
        )
        info.setWordWrap(True)
        info.setObjectName("SmallMuted")
        layout.addWidget(info)

        form = QFormLayout()
        self.provider_combo = QComboBox()
        for pid, p in PROVIDERS.items():
            label = str(p["label"])
            if not p.get("free"):
                label += " (paid)"
            self.provider_combo.addItem(label, pid)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        form.addRow("Provider", self.provider_combo)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("OpenAI-compatible endpoint URL")
        form.addRow("API URL", self.url_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("model name, e.g. llama-3.3-70b-versatile")
        form.addRow("Model", self.model_edit)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("not needed for Ollama")
        form.addRow("API key", self.key_edit)
        layout.addLayout(form)

        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        layout.addWidget(self.test_result)

        row = QHBoxLayout()
        test_btn = QPushButton("Test connection")
        test_btn.clicked.connect(self._test)
        save_btn = QPushButton("Save & enable")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(test_btn)
        row.addStretch(1)
        row.addWidget(save_btn)
        row.addWidget(cancel_btn)
        layout.addLayout(row)

        self._prefill()

    def _prefill(self):
        llm = self.engine.llm
        provider = llm.provider or "custom"
        idx = self.provider_combo.findData(provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.url_edit.setText(llm.url or "")
        self.model_edit.setText(llm.model or "")
        self.key_edit.setText(llm.api_key or "")
        self._provider_changed()

    def _provider_changed(self):
        pid = self.provider_combo.currentData()
        preset = PROVIDERS.get(pid)
        if preset:
            self.url_edit.setText(str(preset["url"]))
            if preset.get("model"):
                self.model_edit.setText(str(preset["model"]))
            needs_key = bool(preset.get("key"))
            self.key_edit.setEnabled(needs_key)
            self.key_edit.setPlaceholderText("not needed for Ollama" if not needs_key
                                             else "free API key from the provider")
            self.url_edit.setEnabled(pid == "custom")
        else:
            self.url_edit.setEnabled(True)
            self.key_edit.setEnabled(True)

    def _values(self):
        pid = self.provider_combo.currentData()
        preset = PROVIDERS.get(pid)
        url = self.url_edit.text().strip()
        if preset and pid != "custom":
            url = str(preset["url"])
        return pid, url, self.model_edit.text().strip(), self.key_edit.text().strip()

    def _test(self):
        pid, url, model, key = self._values()
        if not url or not model:
            self.test_result.setText("Choose a provider and make sure the model name is filled in.")
            return
        self.test_result.setText("Testing…")
        llm = LLMAssistant(provider=pid, url=url, model=model, api_key=key)
        ans = llm.chat("Reply with the single word OK.", "connection test", timeout=20)
        if ans:
            self.test_result.setText(f"Connected to {model} — reply: {ans.strip()[:60]}")
        else:
            self.test_result.setText("Connection failed — check the URL, model name and key (or that Ollama is running).")

    def _save(self):
        pid, url, model, key = self._values()
        if not model:
            self.test_result.setText("Enter a model name before saving.")
            return
        self.engine.configure_llm(provider=pid, url=url, model=model, api_key=key, persist=True)
        if self.on_configured:
            self.on_configured()
        self.accept()


class AssistantTab(QWidget):
    def __init__(self, engine: AssistantEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._ctx = AssistantContext()
        self._memory: Dict[str, object] = {}
        self._history: List[Tuple[str, str]] = []  # (role, text)
        self._worker: Optional[_LLMWorker] = None
        self._fallback_note_shown = False
        self._last_question = ""

        outer = QVBoxLayout(self)
        outer.setSpacing(8)

        header = QGroupBox("AI Assistant")
        hb = QHBoxLayout(header)
        self.mode_label = QLabel(self.engine.mode_label())
        self.mode_label.setObjectName("SmallMuted")
        clear_btn = QPushButton("Clear chat")
        clear_btn.clicked.connect(self.clear)
        settings_btn = QPushButton("AI settings")
        settings_btn.clicked.connect(self._open_settings)
        hb.addWidget(QLabel("Ask about your data — follow up with \"why?\", \"more\", \"and sleep?\"."), 1)
        hb.addWidget(self.mode_label)
        hb.addWidget(clear_btn)
        hb.addWidget(settings_btn)
        outer.addWidget(header)

        self.messages = QListWidget()
        self.messages.setFrameShape(QFrame.Shape.NoFrame)
        self.messages.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.messages.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.messages.setMinimumHeight(320)
        outer.addWidget(self.messages, 1)

        chips = QHBoxLayout()
        for q in QUICK_QUESTIONS:
            b = QPushButton(q)
            b.clicked.connect(lambda _=False, text=q: self.ask(text))
            chips.addWidget(b)
        outer.addLayout(chips)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a question about your data…")
        self.input.returnPressed.connect(self._on_submit)
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._on_submit)
        row.addWidget(self.input, 1)
        row.addWidget(send_btn)
        outer.addLayout(row)

        self._welcome()

    # ------------------------------------------------------------ state
    def refresh_context(self, fv: Optional[FeatureVector], profile: Optional[UserProfile],
                        result: Optional[RiskResult], baseline=None, anomalies=None,
                        recs=None, live_mode: str = "none"):
        self._ctx = AssistantContext(
            fv=fv,
            profile=profile,
            result=result,
            baseline=baseline,
            anomalies=list(anomalies or []),
            recs=list(recs or []),
            live_mode=live_mode,
        )

    def _open_settings(self):
        dlg = AISettingsDialog(self.engine, on_configured=self._refresh_mode, parent=self)
        dlg.exec()

    def _refresh_mode(self):
        self.mode_label.setText(self.engine.mode_label())

    def clear(self):
        self._history = []
        self._memory = {}
        self._fallback_note_shown = False
        self._welcome()

    def _welcome(self):
        self._append("assistant", "Hi! I'm your CHRONO-PCOS assistant. I answer from your "
                                  "real computed data — risk, what's driving it, sleep, stress, "
                                  "anomalies, trends and recommendations. Try a quick question "
                                  "below, or say \"why?\" / \"more\" after an answer to go deeper.")

    # ------------------------------------------------------------ chat flow
    def _on_submit(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.ask(text)

    def ask(self, question: str):
        question = question.strip()
        if not question:
            return
        self._append("user", question)
        self._last_question = question
        # Prevent a stale worker from overwriting a newer answer.
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
        if self.engine.llm.available:
            self._append("assistant", "Thinking…")
            self._worker = _LLMWorker(self.engine, question, self.engine.context_text(self._ctx))
            self._worker.done.connect(self._on_llm_done)
            self._worker.start()
        else:
            answer, topic = self.engine.local.answer(question, self._ctx, self._memory)
            if topic:
                self._memory["last_topic"] = topic
            self._append("assistant", answer)

    def _on_llm_done(self, answer: str):
        # Replace the trailing "Thinking…" placeholder.
        for i in range(len(self._history) - 1, -1, -1):
            role, text = self._history[i]
            if role == "assistant" and text == "Thinking…":
                if answer:
                    self._memory["last_topic"] = self.engine.local.topic_of(self._last_question) or ""
                    self._history[i] = ("assistant", answer)
                else:
                    q = self._history[i - 1][1] if i >= 1 else ""
                    note = " (LLM unavailable — answered locally)" if not self._fallback_note_shown else ""
                    self._fallback_note_shown = True
                    local_answer, topic = self.engine.local.answer(q, self._ctx, self._memory)
                    if topic:
                        self._memory["last_topic"] = topic
                    self._history[i] = ("assistant", local_answer + note)
                break
        self._render()

    def _append(self, role: str, text: str):
        self._history.append((role, text))
        self._render()

    def _render(self):
        self.messages.clear()
        max_w = int(max(240, self.messages.viewport().width() * 0.78))
        for role, text in self._history:
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            bubble = QLabel(_rich(text))
            bubble.setTextFormat(Qt.TextFormat.RichText)
            bubble.setWordWrap(True)
            bubble.setMaximumWidth(max_w)
            bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if role == "user":
                bubble.setStyleSheet(
                    "QLabel { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                    "stop:0 #2f7fd6, stop:1 #5b6cf0); color:#ffffff; border-radius:14px; "
                    "padding:9px 14px; font-size:11pt; }")
            else:
                from src.ui import theme as _theme
                bubble.setStyleSheet(
                    f"QLabel {{ background:{_theme.color('panel_alt')}; "
                    f"border:1px solid {_theme.color('border_light')}; color:{_theme.color('text')}; "
                    "border-radius:14px; padding:9px 14px; font-size:11pt; }")
            container = QWidget()
            lay = QHBoxLayout(container)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            if role == "user":
                lay.addStretch(1)
                lay.addWidget(bubble, 0, Qt.AlignmentFlag.AlignTop)
            else:
                lay.addWidget(bubble, 0, Qt.AlignmentFlag.AlignTop)
                lay.addStretch(1)
            container.setStyleSheet("QWidget { background: transparent; }")
            item.setSizeHint(container.sizeHint())
            self.messages.addItem(item)
            self.messages.setItemWidget(item, container)
        self.messages.scrollToBottom()
