#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml


def _bootstrap_src_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = project_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


def _load_optional_runtime_env() -> None:
    env_file = Path("/etc/default/vicidial-vosk-cobranza-ivr")
    if not env_file.exists():
        return

    target_vars = ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID")
    if all(os.getenv(variable_name) for variable_name in target_vars):
        return

    try:
        env_lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in env_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in target_vars or os.getenv(key):
            continue
        os.environ[key] = value.strip().strip("'").strip('"')


_bootstrap_src_path()
_load_optional_runtime_env()

from vicidial_vosk_cobranza_ivr.config import PROJECT_ROOT  # noqa: E402
from vicidial_vosk_cobranza_ivr.name_audio_cache import (  # noqa: E402
    get_cached_name_audio,
    get_or_generate_name_audio,
)


def load_config() -> dict[str, object]:
    config_path = PROJECT_ROOT / "config" / "ivr.yml"
    with config_path.open("r", encoding="utf-8") as file_handler:
        config_data = yaml.safe_load(file_handler) or {}
    if not isinstance(config_data, dict):
        raise SystemExit("config/ivr.yml debe contener un objeto YAML.")
    return config_data


def build_playback_path(audio_path: Path | None, config: dict[str, object]) -> str:
    if audio_path is None:
        return ""
    name_audio_config = config.get("name_audio", {})
    if not isinstance(name_audio_config, dict):
        name_audio_config = {}
    playback_prefix = str(name_audio_config.get("playback_prefix", "custom/generated/names"))
    playback_prefix = playback_prefix.strip("/")
    return f"{playback_prefix}/{audio_path.stem}"


def main() -> int:
    if len(sys.argv) != 2:
        print('Uso: python scripts/test_name_cache.py "Juan Pérez"', file=sys.stderr)
        return 1

    client_name = sys.argv[1]
    config = load_config()
    cached_before = get_cached_name_audio(client_name, config)
    audio_path = get_or_generate_name_audio(client_name, config)
    generated = audio_path is not None and cached_before is None
    playback_path = build_playback_path(audio_path, config)
    wav_path = str(audio_path) if audio_path is not None else ""

    print(f"generated={'true' if generated else 'false'}")
    print(f"playback_path={playback_path}")
    print(f"wav_path={wav_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
