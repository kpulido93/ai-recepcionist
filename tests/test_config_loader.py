from __future__ import annotations

from pathlib import Path

import yaml

from vicidial_vosk_cobranza_ivr.config import DEFAULT_EVENTS_PATH, load_app_config


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_load_app_config_reads_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "ivr.yml"
    intents_path = tmp_path / "intents.yml"
    write_text(
        config_path,
        """
audio:
  min_rms: 175.0
ivr:
  listen_seconds: 5
  sample_rate: 8000
  retry_attempts: 1
  default_intent: "DUDA"
  allow_dtmf_fallback: true
  early_detection_enabled: true
  early_detection_min_audio_ms: 250
  early_detection_min_chars: 2
  vad_enabled: true
  min_speech_ms: 250
  silence_after_speech_ms: 700
  rms_speech_threshold: 250.0
  max_dtmf_wait_ms: 3000
  dtmf_map:
    "1": "SI"
asterisk:
  app_name: "demo"
  channel_variable_name: "VOSK_INTENT"
  transfer_context: "demo"
  lawyer_destination_type: "ingroup"
  lawyer_destination: "ABOGADOS"
  final_disposition_yes: "Y"
  final_disposition_no: "N"
  final_disposition_unknown: "U"
vosk:
  websocket_url: "ws://127.0.0.1:2700"
  audio_format: "s16le"
  language: "es"
  websocket_timeout_seconds: 10
logging:
  enabled: true
  log_level: "INFO"
  log_path: "./logs/test.log"
  events_path: "/tmp/vosk-events.jsonl"
  log_transcript: false
  mask_phone_numbers: true
  rotate_max_bytes: 2048
  rotate_backup_count: 3
debug:
  audio_dump_enabled: true
  audio_dump_dir: "/tmp/vosk-debug"
prompts:
  personalized_greeting_enabled: true
  greeting_template: "Hola {client_name}, llamada por {bank_name}."
  greeting_template_without_name: "Hola, llamada por {bank_name}."
  greeting_fallback: "Hola, llamada generica."
  generated_audio_dir: "/tmp/generated-prompts"
  generated_audio_playback_prefix: "custom/generated"
  tts_provider: "espeak-ng"
  tts_voice: "es-la"
  cache_enabled: true
""".strip(),
    )
    write_text(
        intents_path,
        """
"SI": ["si"]
"NO": ["no"]
"DUDA": ["quien habla"]
"SILENCIO": []
""".strip(),
    )

    config = load_app_config(config_path, intents_path)

    assert config.audio.min_rms == 175.0
    assert config.ivr.listen_seconds == 5
    assert config.ivr.sample_rate == 8000
    assert config.ivr.early_detection_enabled is True
    assert config.ivr.early_detection_min_audio_ms == 250
    assert config.ivr.early_detection_min_chars == 2
    assert config.ivr.vad_enabled is True
    assert config.ivr.min_speech_ms == 250
    assert config.ivr.silence_after_speech_ms == 700
    assert config.ivr.rms_speech_threshold == 250.0
    assert config.vosk.sample_rate == 8000
    assert config.vosk.websocket_url == "ws://127.0.0.1:2700"
    assert config.intents["SI"] == ["si"]
    assert config.intents["NO"] == ["no"]
    assert config.logging.log_transcript is False
    assert config.logging.mask_phone_numbers is True
    assert config.logging.events_path == "/tmp/vosk-events.jsonl"
    assert config.logging.debug_audio_dump_enabled is True
    assert config.logging.debug_audio_dump_dir == "/tmp/vosk-debug"
    assert config.logging.rotate_max_bytes == 2048
    assert config.logging.rotate_backup_count == 3
    assert config.prompts.personalized_greeting_enabled is True
    assert config.prompts.greeting_template == "Hola {client_name}, llamada por {bank_name}."
    assert config.prompts.greeting_template_without_name == "Hola, llamada por {bank_name}."
    assert config.prompts.greeting_fallback == "Hola, llamada generica."
    assert config.prompts.generated_audio_dir == "/tmp/generated-prompts"
    assert config.prompts.generated_audio_playback_prefix == "custom/generated"
    assert config.prompts.tts_provider == "espeak-ng"
    assert config.prompts.tts_voice == "es-la"
    assert config.prompts.cache_enabled is True


def test_load_app_config_supports_legacy_yaml_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "ivr.yml"
    intents_path = tmp_path / "intents.yml"
    write_text(
        config_path,
        """
audio:
  min_rms: 175.0
ivr:
  listen_seconds: 4
  retry_attempts: 1
  default_intent: "DUDA"
  allow_dtmf_fallback: true
  max_dtmf_wait_ms: 3000
  dtmf_map:
    "1": "SI"
asterisk:
  app_name: "demo"
  channel_variable_name: "VOSK_INTENT"
  transfer_context: "demo"
  lawyer_destination_type: "ingroup"
  lawyer_destination: "ABOGADOS"
  final_disposition_yes: "Y"
  final_disposition_no: "N"
  final_disposition_unknown: "U"
vosk:
  websocket_url: "ws://127.0.0.1:2700"
  sample_rate: 8000
  audio_format: "s16le"
  language: "es"
  websocket_timeout_seconds: 10
logging:
  enabled: true
  log_level: "INFO"
  log_path: "./logs/test.log"
  log_transcript: false
  mask_phone_numbers: true
  debug_audio_dump_enabled: true
  debug_audio_dump_dir: "/tmp/vosk-debug"
  rotate_max_bytes: 2048
  rotate_backup_count: 3
""".strip(),
    )
    write_text(
        intents_path,
        """
"SI": ["si"]
"NO": ["no"]
"DUDA": ["quien habla"]
"SILENCIO": []
""".strip(),
    )

    config = load_app_config(config_path, intents_path)

    assert config.ivr.listen_seconds == 4
    assert config.ivr.sample_rate == 8000
    assert config.vosk.sample_rate == 8000
    assert config.ivr.early_detection_enabled is True
    assert config.ivr.vad_enabled is True
    assert config.logging.mask_phone_numbers is True
    assert config.logging.events_path == DEFAULT_EVENTS_PATH
    assert config.logging.debug_audio_dump_enabled is True
    assert config.logging.debug_audio_dump_dir == "/tmp/vosk-debug"


def test_load_app_config_applies_level1_defaults_when_keys_are_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "ivr.yml"
    intents_path = tmp_path / "intents.yml"
    write_text(
        config_path,
        """
audio:
  min_rms: 175.0
ivr:
  retry_attempts: 1
  default_intent: "DUDA"
  allow_dtmf_fallback: true
  max_dtmf_wait_ms: 3000
  dtmf_map:
    "1": "SI"
asterisk:
  app_name: "demo"
  channel_variable_name: "VOSK_INTENT"
  transfer_context: "demo"
  lawyer_destination_type: "ingroup"
  lawyer_destination: "ABOGADOS"
  final_disposition_yes: "Y"
  final_disposition_no: "N"
  final_disposition_unknown: "U"
vosk:
  websocket_url: "ws://127.0.0.1:2700"
  audio_format: "s16le"
  language: "es"
  websocket_timeout_seconds: 10
logging:
  enabled: true
  log_level: "INFO"
  log_path: "./logs/test.log"
  log_transcript: false
  rotate_max_bytes: 2048
  rotate_backup_count: 3
""".strip(),
    )
    write_text(
        intents_path,
        """
"SI": ["si"]
"NO": ["no"]
"DUDA": ["quien habla"]
"SILENCIO": []
""".strip(),
    )

    config = load_app_config(config_path, intents_path)

    assert config.ivr.listen_seconds == 5
    assert config.ivr.sample_rate == 8000
    assert config.vosk.sample_rate == 8000
    assert config.ivr.early_detection_enabled is True
    assert config.ivr.early_detection_min_audio_ms == 250
    assert config.ivr.early_detection_min_chars == 2
    assert config.ivr.vad_enabled is True
    assert config.ivr.min_speech_ms == 250
    assert config.ivr.silence_after_speech_ms == 700
    assert config.ivr.rms_speech_threshold == 250.0
    assert config.logging.mask_phone_numbers is True
    assert config.logging.events_path == DEFAULT_EVENTS_PATH
    assert config.logging.debug_audio_dump_enabled is False
    assert config.logging.debug_audio_dump_dir == "/tmp"
    assert config.prompts.personalized_greeting_enabled is False
    assert config.prompts.cache_enabled is True


def test_load_app_config_preserves_quoted_no_intent_key_as_string(tmp_path: Path) -> None:
    config_path = tmp_path / "ivr.yml"
    intents_path = tmp_path / "intents.yml"
    write_text(
        config_path,
        """
audio:
  min_rms: 175.0
ivr:
  listen_seconds: 5
  retry_attempts: 1
  default_intent: "DUDA"
  allow_dtmf_fallback: true
  max_dtmf_wait_ms: 3000
  dtmf_map:
    "1": "SI"
asterisk:
  app_name: "demo"
  channel_variable_name: "VOSK_INTENT"
  transfer_context: "demo"
  lawyer_destination_type: "ingroup"
  lawyer_destination: "ABOGADOS"
  final_disposition_yes: "Y"
  final_disposition_no: "N"
  final_disposition_unknown: "U"
vosk:
  websocket_url: "ws://127.0.0.1:2700"
  sample_rate: 8000
  audio_format: "s16le"
  language: "es"
  websocket_timeout_seconds: 10
logging:
  enabled: true
  log_level: "INFO"
  log_path: "./logs/test.log"
  log_transcript: false
  mask_phone_numbers: true
  rotate_max_bytes: 2048
  rotate_backup_count: 3
""".strip(),
    )
    write_text(
        intents_path,
        """
"SI": ["si"]
"NO": ["no me transfiera"]
"DUDA": ["quien habla"]
"SILENCIO": []
""".strip(),
    )

    raw_intents = yaml.safe_load(intents_path.read_text(encoding="utf-8"))
    config = load_app_config(config_path, intents_path)

    assert "NO" in raw_intents
    assert not any(isinstance(key, bool) for key in raw_intents)
    assert config.intents["NO"] == ["no me transfiera"]


def test_load_app_config_allows_missing_info_cobro_key(tmp_path: Path) -> None:
    config_path = tmp_path / "ivr.yml"
    intents_path = tmp_path / "intents.yml"
    write_text(
        config_path,
        """
audio:
  min_rms: 175.0
ivr:
  listen_seconds: 5
  retry_attempts: 1
  default_intent: "DUDA"
  allow_dtmf_fallback: true
  max_dtmf_wait_ms: 3000
  dtmf_map:
    "1": "SI"
asterisk:
  app_name: "demo"
  channel_variable_name: "VOSK_INTENT"
  transfer_context: "demo"
  lawyer_destination_type: "ingroup"
  lawyer_destination: "ABOGADOS"
  final_disposition_yes: "Y"
  final_disposition_no: "N"
  final_disposition_unknown: "U"
vosk:
  websocket_url: "ws://127.0.0.1:2700"
  sample_rate: 8000
  audio_format: "s16le"
  language: "es"
  websocket_timeout_seconds: 10
logging:
  enabled: true
  log_level: "INFO"
  log_path: "./logs/test.log"
  log_transcript: false
  mask_phone_numbers: true
  rotate_max_bytes: 2048
  rotate_backup_count: 3
""".strip(),
    )
    write_text(
        intents_path,
        """
"SI": ["si"]
"NO": ["no"]
"DUDA": ["quien habla"]
"SILENCIO": []
""".strip(),
    )

    config = load_app_config(config_path, intents_path)

    assert config.intents["SI"] == ["si"]
    assert "INFO_COBRO" not in config.intents


def test_load_app_config_applies_env_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "ivr.yml"
    intents_path = tmp_path / "intents.yml"
    write_text(
        config_path,
        """
audio:
  min_rms: 175.0
ivr:
  listen_seconds: 4
  retry_attempts: 1
  default_intent: "DUDA"
  allow_dtmf_fallback: true
  max_dtmf_wait_ms: 3000
  dtmf_map:
    "1": "SI"
asterisk:
  app_name: "demo"
  channel_variable_name: "VOSK_INTENT"
  transfer_context: "demo"
  lawyer_destination_type: "ingroup"
  lawyer_destination: "ABOGADOS"
  final_disposition_yes: "Y"
  final_disposition_no: "N"
  final_disposition_unknown: "U"
vosk:
  websocket_url: "ws://127.0.0.1:2700"
  sample_rate: 8000
  audio_format: "s16le"
  language: "es"
  websocket_timeout_seconds: 10
logging:
  enabled: true
  log_level: "INFO"
  log_path: "./logs/test.log"
  log_transcript: false
  mask_phone_numbers: true
  rotate_max_bytes: 2048
  rotate_backup_count: 3
""".strip(),
    )
    write_text(
        intents_path,
        """
"SI": ["si"]
"NO": ["no"]
"DUDA": ["quien habla"]
"SILENCIO": []
""".strip(),
    )
    monkeypatch.setenv("VOSK_WEBSOCKET_URL", "ws://vosk.example.invalid:2700")
    monkeypatch.setenv("VOSK_SAMPLE_RATE", "16000")
    monkeypatch.setenv("VOSK_WEBSOCKET_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("IVR_LISTEN_SECONDS", "3")
    monkeypatch.setenv("VOSK_MIN_RMS", "210.5")
    monkeypatch.setenv("LOG_TRANSCRIPT", "true")
    monkeypatch.setenv("LOG_ROTATE_MAX_BYTES", "4096")

    config = load_app_config(config_path, intents_path)

    assert config.audio.min_rms == 210.5
    assert config.vosk.websocket_url == "ws://vosk.example.invalid:2700"
    assert config.ivr.sample_rate == 16000
    assert config.vosk.sample_rate == 16000
    assert config.vosk.websocket_timeout_seconds == 12
    assert config.ivr.listen_seconds == 3
    assert config.logging.events_path == DEFAULT_EVENTS_PATH
    assert config.logging.log_transcript is True
    assert config.logging.rotate_max_bytes == 4096


def test_load_app_config_reads_events_path_from_logging_yml(tmp_path: Path) -> None:
    config_path = tmp_path / "ivr.yml"
    intents_path = tmp_path / "intents.yml"
    logging_path = tmp_path / "logging.yml"
    write_text(
        config_path,
        """
audio:
  min_rms: 175.0
ivr:
  retry_attempts: 1
  default_intent: "DUDA"
  allow_dtmf_fallback: true
  max_dtmf_wait_ms: 3000
  dtmf_map:
    "1": "SI"
asterisk:
  app_name: "demo"
  channel_variable_name: "VOSK_INTENT"
  transfer_context: "demo"
  lawyer_destination_type: "ingroup"
  lawyer_destination: "ABOGADOS"
  final_disposition_yes: "Y"
  final_disposition_no: "N"
  final_disposition_unknown: "U"
vosk:
  websocket_url: "ws://127.0.0.1:2700"
  sample_rate: 8000
  audio_format: "s16le"
  language: "es"
  websocket_timeout_seconds: 10
logging:
  enabled: true
  log_level: "INFO"
  log_path: "./logs/test.log"
  log_transcript: false
  mask_phone_numbers: true
  rotate_max_bytes: 2048
  rotate_backup_count: 3
""".strip(),
    )
    write_text(
        intents_path,
        """
"SI": ["si"]
"NO": ["no"]
"DUDA": ["quien habla"]
"SILENCIO": []
""".strip(),
    )
    write_text(
        logging_path,
        """
version: 1
handlers: {}
root:
  handlers: []
  level: INFO
reporting:
  events_path: "/tmp/events-from-logging.jsonl"
""".strip(),
    )

    config = load_app_config(config_path, intents_path, logging_path)

    assert config.logging.events_path == "/tmp/events-from-logging.jsonl"
