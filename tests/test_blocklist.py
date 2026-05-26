from __future__ import annotations

from pathlib import Path

from vicidial_vosk_cobranza_ivr.blocklist import (
    BlocklistMatcher,
    load_blocklist_config,
    sanitize_blocklist_match,
)


def test_sanitize_blocklist_match_redacts_original_text() -> None:
    assert sanitize_blocklist_match("__ABUSIVE_TOKEN__") == "redacted[13]"


def test_blocklist_matcher_finds_abusive_term() -> None:
    matcher = BlocklistMatcher.from_mapping(
        {
            "abusive_language": {
                "enabled": True,
                "terms": ["__ABUSIVE_TOKEN__"],
                "phrases": [],
            }
        }
    )

    match = matcher.match("__ABUSIVE_TOKEN__ quiero hablar")

    assert match is not None
    assert match.intent == "VULGARIDAD"
    assert match.category == "abusive_language"
    assert match.matched_value == "redacted[13]"


def test_load_blocklist_config_merges_local_overrides(tmp_path: Path) -> None:
    sample_path = tmp_path / "blocklist.sample.yml"
    local_path = tmp_path / "blocklist.yml"
    sample_path.write_text(
        """
abusive_language:
  enabled: true
  terms: []
  phrases: []
verbal_threats:
  enabled: true
  terms: []
  phrases: []
""".strip(),
        encoding="utf-8",
    )
    local_path.write_text(
        """
abusive_language:
  terms:
    - "__ABUSIVE_TOKEN__"
""".strip(),
        encoding="utf-8",
    )

    config = load_blocklist_config(sample_path=sample_path, local_path=local_path)

    assert config.abusive_language.terms == ("abusive token",)
