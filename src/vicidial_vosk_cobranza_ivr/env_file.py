from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

ELEVENLABS_API_KEY_ENV = "ELEVENLABS_API_KEY"
ELEVENLABS_VOICE_ID_ENV = "ELEVENLABS_VOICE_ID"
SUPPORTED_ELEVENLABS_ENV_VARS = frozenset({ELEVENLABS_API_KEY_ENV, ELEVENLABS_VOICE_ID_ENV})
ENV_ASSIGNMENT_PATTERN = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


@dataclass(frozen=True)
class EnvFileLoadStatus:
    path: Path | None
    attempted: bool
    loaded_api_key: bool
    loaded_voice_id: bool
    had_error: bool = False


def parse_env_file(
    path: str | Path,
    *,
    allowed_keys: Iterable[str] | None = None,
) -> dict[str, str]:
    resolved_path = Path(path).expanduser().resolve()
    allowed_key_set = set(allowed_keys or ())
    env_values: dict[str, str] = {}

    for raw_line in resolved_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        match = ENV_ASSIGNMENT_PATTERN.match(line)
        if match is None:
            continue

        key = match.group(1)
        value = _strip_optional_quotes(match.group(2).strip())
        if allowed_key_set and key not in allowed_key_set:
            continue
        env_values[key] = value

    return env_values


def load_env_file(
    path: str | Path,
    *,
    allowed_keys: Iterable[str] | None = None,
    override: bool = False,
) -> set[str]:
    parsed_values = parse_env_file(path, allowed_keys=allowed_keys)
    loaded_keys: set[str] = set()
    for key, value in parsed_values.items():
        if not override and os.getenv(key):
            continue
        os.environ[key] = value
        loaded_keys.add(key)
    return loaded_keys


def resolve_env_file_path(
    raw_path: str | Path,
    config: Mapping[str, object] | None = None,
) -> Path:
    env_file_path = Path(str(raw_path)).expanduser()
    if env_file_path.is_absolute():
        return env_file_path.resolve()

    config_path = None if config is None else config.get("__config_path__")
    if config_path:
        config_file_path = Path(str(config_path)).expanduser().resolve()
        return (config_file_path.parent / env_file_path).resolve()

    return env_file_path.resolve()


def get_optima_env_file_path(config: Mapping[str, object]) -> Path | None:
    optima_audio_config = config.get("optima_audio")
    if not isinstance(optima_audio_config, Mapping):
        return None

    raw_env_file = optima_audio_config.get("env_file")
    if raw_env_file is None:
        return None
    normalized_env_file = str(raw_env_file).strip()
    if not normalized_env_file:
        return None

    return resolve_env_file_path(normalized_env_file, config)


def load_optima_env_file_if_needed(
    config: Mapping[str, object],
    *,
    explicit_env_file: str | Path | None = None,
) -> EnvFileLoadStatus:
    if os.getenv(ELEVENLABS_API_KEY_ENV) and os.getenv(ELEVENLABS_VOICE_ID_ENV):
        return EnvFileLoadStatus(
            path=None,
            attempted=False,
            loaded_api_key=False,
            loaded_voice_id=False,
        )

    resolved_path = _resolve_candidate_env_file(config, explicit_env_file)
    if resolved_path is None:
        return EnvFileLoadStatus(
            path=None,
            attempted=False,
            loaded_api_key=False,
            loaded_voice_id=False,
        )

    try:
        loaded_keys = load_env_file(
            resolved_path,
            allowed_keys=SUPPORTED_ELEVENLABS_ENV_VARS,
            override=False,
        )
    except OSError:
        return EnvFileLoadStatus(
            path=resolved_path,
            attempted=True,
            loaded_api_key=False,
            loaded_voice_id=False,
            had_error=True,
        )

    return EnvFileLoadStatus(
        path=resolved_path,
        attempted=True,
        loaded_api_key=ELEVENLABS_API_KEY_ENV in loaded_keys,
        loaded_voice_id=ELEVENLABS_VOICE_ID_ENV in loaded_keys,
    )


def _resolve_candidate_env_file(
    config: Mapping[str, object],
    explicit_env_file: str | Path | None,
) -> Path | None:
    if explicit_env_file is not None and str(explicit_env_file).strip():
        return resolve_env_file_path(explicit_env_file, config)
    return get_optima_env_file_path(config)


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
