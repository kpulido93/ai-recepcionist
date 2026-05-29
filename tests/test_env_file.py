from __future__ import annotations

import os
from pathlib import Path

from pytest import MonkeyPatch

from vicidial_vosk_cobranza_ivr.env_file import (
    ELEVENLABS_API_KEY_ENV,
    ELEVENLABS_VOICE_ID_ENV,
    load_optima_env_file_if_needed,
    parse_env_file,
    resolve_env_file_path,
)


def test_parse_env_file_supports_export_quotes_and_comments(tmp_path: Path) -> None:
    env_file = tmp_path / "elevenlabs.env"
    env_file.write_text(
        """
# comentario
export ELEVENLABS_API_KEY="test-key"
ELEVENLABS_VOICE_ID='voice-demo'
IGNORED_VALUE=123
INVALID LINE
""".strip(),
        encoding="utf-8",
    )

    parsed = parse_env_file(
        env_file,
        allowed_keys={ELEVENLABS_API_KEY_ENV, ELEVENLABS_VOICE_ID_ENV},
    )

    assert parsed == {
        ELEVENLABS_API_KEY_ENV: "test-key",
        ELEVENLABS_VOICE_ID_ENV: "voice-demo",
    }


def test_resolve_env_file_path_uses_config_path_for_relative_paths(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "ivr.yml"
    config_path.write_text("{}", encoding="utf-8")

    resolved_path = resolve_env_file_path(
        "secrets/elevenlabs.env",
        {"__config_path__": str(config_path)},
    )

    assert resolved_path == (config_dir / "secrets" / "elevenlabs.env").resolve()


def test_load_optima_env_file_if_needed_loads_key_and_voice_id(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    env_file = tmp_path / "elevenlabs.env"
    env_file.write_text(
        """
export ELEVENLABS_API_KEY=test-key
ELEVENLABS_VOICE_ID=voice-demo
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv(ELEVENLABS_API_KEY_ENV, raising=False)
    monkeypatch.delenv(ELEVENLABS_VOICE_ID_ENV, raising=False)

    status = load_optima_env_file_if_needed(
        {"optima_audio": {"env_file": str(env_file)}},
    )

    assert status.attempted is True
    assert status.loaded_api_key is True
    assert status.loaded_voice_id is True
    assert os.getenv(ELEVENLABS_API_KEY_ENV) == "test-key"
    assert os.getenv(ELEVENLABS_VOICE_ID_ENV) == "voice-demo"


def test_load_optima_env_file_if_needed_skips_when_env_already_exists(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    env_file = tmp_path / "elevenlabs.env"
    env_file.write_text("ELEVENLABS_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setenv(ELEVENLABS_API_KEY_ENV, "env-key")
    monkeypatch.setenv(ELEVENLABS_VOICE_ID_ENV, "env-voice")

    status = load_optima_env_file_if_needed(
        {"optima_audio": {"env_file": str(env_file)}},
    )

    assert status.attempted is False
    assert status.loaded_api_key is False
    assert status.loaded_voice_id is False
    assert os.getenv(ELEVENLABS_API_KEY_ENV) == "env-key"
