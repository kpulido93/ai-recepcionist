from __future__ import annotations

from pathlib import Path

from vicidial_vosk_cobranza_ivr.config import load_app_config


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
SI: ["si"]
NO: ["no"]
DUDA: ["quien habla"]
SILENCIO: []
""".strip(),
    )

    config = load_app_config(config_path, intents_path)

    assert config.audio.min_rms == 175.0
    assert config.ivr.listen_seconds == 5
    assert config.vosk.websocket_url == "ws://127.0.0.1:2700"
    assert config.intents["SI"] == ["si"]
    assert config.logging.log_transcript is False
    assert config.logging.rotate_max_bytes == 2048
    assert config.logging.rotate_backup_count == 3


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
SI: ["si"]
NO: ["no"]
DUDA: ["quien habla"]
SILENCIO: []
""".strip(),
    )
    monkeypatch.setenv("VOSK_WEBSOCKET_URL", "ws://10.20.30.40:2700")
    monkeypatch.setenv("IVR_LISTEN_SECONDS", "3")
    monkeypatch.setenv("VOSK_MIN_RMS", "210.5")
    monkeypatch.setenv("LOG_TRANSCRIPT", "true")
    monkeypatch.setenv("LOG_ROTATE_MAX_BYTES", "4096")

    config = load_app_config(config_path, intents_path)

    assert config.audio.min_rms == 210.5
    assert config.vosk.websocket_url == "ws://10.20.30.40:2700"
    assert config.ivr.listen_seconds == 3
    assert config.logging.log_transcript is True
    assert config.logging.rotate_max_bytes == 4096
