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
  mask_phone_numbers: true
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

    assert config.ivr.listen_seconds == 5
    assert config.vosk.websocket_url == "ws://127.0.0.1:2700"
    assert config.intents["SI"] == ["si"]


def test_load_app_config_applies_env_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "ivr.yml"
    intents_path = tmp_path / "intents.yml"
    write_text(
        config_path,
        """
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
  mask_phone_numbers: true
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

    config = load_app_config(config_path, intents_path)

    assert config.vosk.websocket_url == "ws://10.20.30.40:2700"
    assert config.ivr.listen_seconds == 3
