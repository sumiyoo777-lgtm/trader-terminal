"""Kronos Mode B — local model runner.

Delegates inference to the Kronos skill's already-provisioned venv
(~/.claude/skills/kronos/.venv has torch/transformers; the model repo is at
.../kronos/_kronos) by subprocessing scripts/_kronos_path_inner.py inside it.
This backend never imports torch.

If the venv/model is unavailable, `local_kronos_available()` reports why and
the rest of the terminal keeps working with manually imported forecasts.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from .kronos_import import KronosImportError, parse_forecast_json

log = logging.getLogger(__name__)

KRONOS_SKILL_DIR = Path.home() / ".claude" / "skills" / "kronos"
KRONOS_VENV_DIR = KRONOS_SKILL_DIR / ".venv"
KRONOS_REPO_DIR = KRONOS_SKILL_DIR / "_kronos"
INNER_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "_kronos_path_inner.py"

INFER_TIMEOUT_SECONDS = 1800  # CPU ensemble inference can take a while


class KronosLocalError(RuntimeError):
    pass


def _venv_python(venv_dir: Path = KRONOS_VENV_DIR) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python3"


def local_kronos_available(
    model_path: str = "",
    venv_dir: Path = KRONOS_VENV_DIR,
    repo_dir: Path = KRONOS_REPO_DIR,
) -> tuple[bool, str]:
    """(available, reason). KRONOS_MODEL_PATH env overrides the repo dir."""
    repo = Path(model_path) if model_path else repo_dir
    python = _venv_python(venv_dir)
    if not python.exists():
        return False, f"Kronos venv python not found at {python}"
    if not repo.exists():
        return False, f"Kronos model repo not found at {repo}"
    if not INNER_SCRIPT.exists():
        return False, f"inner script missing at {INNER_SCRIPT}"
    return True, "ok"


def _extract_json_line(stdout: str) -> dict | None:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def run_local_forecast(
    ticker: str,
    horizon: str,
    pred_len: int | None = None,
    ensemble_size: int = 3,
    model_path: str = "",
    device: str = "cpu",
    timeout: int = INFER_TIMEOUT_SECONDS,
) -> dict:
    """Run one local Kronos forecast and return the normalized forecast dict
    (same schema as manual import). Raises KronosLocalError with the real
    reason on any failure — never returns fabricated data."""
    available, reason = local_kronos_available(model_path)
    if not available:
        raise KronosLocalError(f"local Kronos unavailable: {reason}")

    cmd = [str(_venv_python()), str(INNER_SCRIPT), ticker, horizon]
    if pred_len:
        cmd.append(str(pred_len))
        cmd.append(str(ensemble_size))

    env = dict(os.environ)
    env["KRONOS_REPO"] = model_path or str(KRONOS_REPO_DIR)
    env["KRONOS_DEVICE"] = device

    log.info("running local Kronos: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise KronosLocalError(f"Kronos inference timed out after {timeout}s") from exc

    if proc.returncode != 0:
        raise KronosLocalError(
            f"Kronos inference failed (exit {proc.returncode}). stderr tail:\n{proc.stderr[-2000:]}"
        )

    payload = _extract_json_line(proc.stdout)
    if payload is None:
        raise KronosLocalError(f"no parseable JSON in Kronos output. stdout tail:\n{proc.stdout[-2000:]}")

    return normalize_runner_payload(payload)


def normalize_runner_payload(payload: dict) -> dict:
    """Validate/normalize the inner script's payload through the same parser
    as manual imports, so both modes produce identical forecast records."""
    try:
        forecast = parse_forecast_json(payload)
    except KronosImportError as exc:
        raise KronosLocalError(f"runner payload failed validation: {exc}") from exc
    forecast["metadata"] = {
        **(forecast.get("metadata") or {}),
        "mode": "local_runner",
        "current_price_at_run": payload.get("current_price"),
    }
    return forecast
