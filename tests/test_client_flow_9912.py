from __future__ import annotations

from pathlib import Path


def test_lab_extensions_keep_9910_and_9911_and_add_9912() -> None:
    dialplan_path = Path("asterisk/extensions_lab.conf.sample")
    dialplan_text = dialplan_path.read_text(encoding="utf-8")

    assert "exten => 9900,1,Goto(ivr-cobranza-vosk,s,1)" in dialplan_text
    assert "exten => 9911,1,Goto(vicidial-vosk-cobranza-ivr-test-name,s,1)" in dialplan_text
    assert "exten => 9912,1,Goto(vicidial-vosk-cobranza-ivr-client-flow,s,1)" in dialplan_text
    assert "[vicidial-vosk-cobranza-ivr-client-flow]" in dialplan_text
