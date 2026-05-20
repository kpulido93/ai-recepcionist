#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap_src_path() -> None:
    for candidate in _candidate_src_roots():
        if str(candidate) in sys.path:
            return
        if candidate.exists():
            sys.path.insert(0, str(candidate))
            return


def _candidate_src_roots() -> list[Path]:
    candidates: list[Path] = []

    # When this AGI is copied into /var/lib/asterisk/agi-bin, __file__ no longer
    # points at the project tree. In production, absolute env paths are safer
    # because they let us infer the real repo root and sibling src/ directory.
    for env_name in (
        "VOSK_COBRANZA_CONFIG",
        "VOSK_COBRANZA_INTENTS",
        "VOSK_COBRANZA_LOGGING",
    ):
        env_value = os.getenv(env_name)
        if not env_value:
            continue
        resolved = Path(env_value).expanduser().resolve()
        project_root = resolved.parents[1] if len(resolved.parents) > 1 else resolved.parent
        candidates.append(project_root / "src")

    script_path = Path(__file__).resolve()
    if len(script_path.parents) > 1:
        candidates.append(script_path.parents[1] / "src")

    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)

    return unique_candidates


def main() -> int:
    _bootstrap_src_path()
    from vicidial_vosk_cobranza_ivr.app import run_eagi

    return run_eagi()


def send_audio_to_vosk(websocket: object, audio_chunk: bytes) -> None:
    _bootstrap_src_path()
    from vicidial_vosk_cobranza_ivr.vosk_client import send_audio_to_vosk as _send_audio_to_vosk

    _send_audio_to_vosk(websocket, audio_chunk)


if __name__ == "__main__":
    raise SystemExit(main())
