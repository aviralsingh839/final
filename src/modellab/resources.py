"""Training-environment detection (CPU / RAM / GPU / CUDA) and feasibility.

Never crashes when hardware is missing — it explains instead.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional


def _ram_gb() -> Optional[float]:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / (1024 * 1024), 1)
    except Exception:
        pass
    try:
        import psutil  # optional

        return round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except Exception:
        return None


def detect_environment() -> dict:
    env = {
        "cpu_count": os.cpu_count() or 1,
        "ram_gb": _ram_gb(),
        "gpu_detected": False,
        "gpu_name": None,
        "gpu_memory_gb": None,
        "cuda_available": False,
        "torch_available": False,
    }
    try:
        import torch  # optional heavyweight dependency

        env["torch_available"] = True
        if torch.cuda.is_available():
            env["cuda_available"] = True
            env["gpu_detected"] = True
            env["gpu_name"] = torch.cuda.get_device_name(0)
            env["gpu_memory_gb"] = round(
                torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, 1)
    except Exception:
        pass
    if not env["gpu_detected"] and shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5)
            line = (out.stdout or "").strip().splitlines()
            if line:
                name, mem = (line[0].split(",") + [""])[:2]
                env["gpu_detected"] = True
                env["gpu_name"] = name.strip()
                try:
                    env["gpu_memory_gb"] = round(float(mem.strip().split()[0]) / 1024, 1)
                except Exception:
                    pass
        except Exception:
            pass
    env["feasibility"] = _feasibility(env)
    return env


def _feasibility(env: dict) -> str:
    if env["gpu_detected"] and env["torch_available"]:
        return "HIGH"
    ram = env["ram_gb"] or 0
    if ram >= 8 and env["cpu_count"] >= 4:
        return "MODERATE"
    return "LOW"


def feasibility_note(env: dict, model_key: str) -> str:
    if model_key == "cnn_transfer" and not (env["torch_available"] and env["gpu_detected"]):
        return ("This training configuration may require a GPU-enabled environment. "
                "The transfer-learning CNN backend needs PyTorch (and ideally CUDA); "
                "choose a lightweight backend to train on this machine.")
    if env["feasibility"] == "LOW":
        return ("Limited local resources detected — training will run on CPU with "
                "the lightweight backends; larger configurations may be slow.")
    return ""
