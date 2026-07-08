"""LLM calls are mocked here — no real network access. Verifies the
cache -> call -> one retry -> deterministic fallback path in src/llm.py."""
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from src import llm as llm_mod


@dataclass
class FakeSettings:
    llm_enabled: bool = True
    openai_api_key: str = "test-key"
    openai_model: str = "test-model"
    openai_base_url: str = ""


@pytest.fixture(autouse=True)
def isolate_llm(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_mod, "SETTINGS", FakeSettings())
    monkeypatch.setattr(llm_mod, "CACHE_PATH", tmp_path / "llm_cache.json")


def fake_response(text: str):
    # Mirrors the shape of client.chat.completions.create(...)'s return value.
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


VALID_NOTE = json.dumps({
    "summary": "Parent unreachable after two attempts.",
    "barrier_type": "contact_failure", "severity": "high",
    "intervention_attempted": "phone calls", "intervention_outcome": "no response",
    "follow_up_needed": True, "topic": "attendance", "confidence": 0.8,
})

INVALID_NOTE = json.dumps({"summary": "missing fields"})  # fails schema validation


def _patch_client(monkeypatch, responses: list):
    """responses: list of return values (str) or Exception instances, consumed in order."""
    calls = {"count": 0}

    class FakeClient:
        class chat:  # noqa: N801 — mirrors openai SDK's `client.chat.completions.create`
            class completions:
                @staticmethod
                def create(**kwargs):
                    i = calls["count"]
                    calls["count"] += 1
                    item = responses[i]
                    if isinstance(item, Exception):
                        raise item
                    return fake_response(item)

    monkeypatch.setattr(llm_mod, "_client", lambda: FakeClient())
    return calls


def test_valid_structured_response_is_accepted(monkeypatch):
    _patch_client(monkeypatch, [VALID_NOTE])
    result, log = llm_mod.analyze_note("N1", "note text", {"student_id": "S1", "grade": 10, "learning_track": "Standard"})
    assert result["barrier_type"] == "contact_failure"
    assert result["severity"] == "high"
    assert log.status == "success"
    assert log.cache_hit is False


def test_invalid_response_triggers_retry_then_succeeds(monkeypatch):
    calls = _patch_client(monkeypatch, [INVALID_NOTE, VALID_NOTE])
    result, log = llm_mod.analyze_note("N2", "note text", {"student_id": "S2", "grade": 10, "learning_track": "Standard"})
    assert calls["count"] == 2  # first attempt failed validation, second (retry) succeeded
    assert result["severity"] == "high"
    assert log.status == "success"


def test_second_failure_uses_deterministic_fallback(monkeypatch):
    calls = _patch_client(monkeypatch, [INVALID_NOTE, INVALID_NOTE])
    note_text = "اتصلت على الام، ما ردت"  # contains a contact_failure keyword for the fallback
    result, log = llm_mod.analyze_note("N3", note_text, {"student_id": "S3", "grade": 10, "learning_track": "Standard"})
    assert calls["count"] == 2  # MAX_RETRIES=1 -> at most 2 attempts total
    assert log.status == "fallback"
    assert result["barrier_type"] == "contact_failure"  # deterministic keyword fallback kicked in
    assert result["confidence"] == 0.5


def test_disabled_llm_never_calls_the_client(monkeypatch):
    monkeypatch.setattr(llm_mod, "SETTINGS", FakeSettings(llm_enabled=False))

    def boom():
        raise AssertionError("should not be called when LLM is disabled")

    monkeypatch.setattr(llm_mod, "_client", boom)
    result, log = llm_mod.analyze_note("N4", "plain note", {"student_id": "S4"})
    assert log.status == "disabled"
    assert "barrier_type" in result
