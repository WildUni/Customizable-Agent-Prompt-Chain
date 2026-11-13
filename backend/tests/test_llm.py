import math
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import config
import llm
from llm import LLMSettings, complete, fake_complete

# ---------- helpers ----------

class FakeClient:
    """Stand-in for OpenAI(): records what it was called with, returns a canned reply."""
    def __init__(self, reply="hello"):
        self.calls = []
        self.reply = reply
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def use_fake_client(monkeypatch, reply="hello"):
    fake = FakeClient(reply)
    monkeypatch.setattr(llm, "client", fake)
    return fake


@pytest.fixture(autouse=True)
def isolate_from_env(monkeypatch):
    """Don't let a developer's .env change test results: real-LLM path, no
    cached client."""
    monkeypatch.setattr(config, "USE_FAKE_LLM", False)
    monkeypatch.setattr(llm, "client", None)


# ---------- get_client ----------

def test_get_client_without_api_key_raises_clear_error(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        complete("hi")


def test_get_client_created_once_and_cached(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPENAI_BASE_URL", "http://localhost:1/v1")
    first = llm.get_client()
    assert llm.get_client() is first
    assert first.api_key == "test-key"


def test_fake_mode_needs_no_api_key(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(config, "USE_FAKE_LLM", True)
    assert complete("hi") == fake_complete("hi")


# ---------- fake_complete ----------

def test_fake_complete_includes_prompt():
    assert "tell me a joke" in fake_complete("tell me a joke")


def test_complete_uses_fake_when_flag_on(monkeypatch):
    fake = use_fake_client(monkeypatch)
    monkeypatch.setattr(config, "USE_FAKE_LLM", True)

    result = complete("hi")

    assert result == fake_complete("hi")
    assert fake.calls == []  # real client never touched


# ---------- complete ----------

def test_complete_returns_model_text(monkeypatch):
    use_fake_client(monkeypatch, reply="Hi there!")
    assert complete("hi") == "Hi there!"


def test_complete_sends_system_prompt_first(monkeypatch):
    fake = use_fake_client(monkeypatch)
    complete("hi", LLMSettings(system="Be brief"))

    messages = fake.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "Be brief"}
    assert messages[1] == {"role": "user", "content": "hi"}


def test_complete_omits_max_tokens_when_none(monkeypatch):
    fake = use_fake_client(monkeypatch)
    complete("hi")
    assert "max_tokens" not in fake.calls[0]


def test_complete_passes_settings(monkeypatch):
    fake = use_fake_client(monkeypatch)
    complete("hi", LLMSettings(model="m1", temperature=0.1, max_tokens=50))

    call = fake.calls[0]
    assert call["model"] == "m1"
    assert call["temperature"] == 0.1
    assert call["max_tokens"] == 50


def test_complete_handles_none_content(monkeypatch):
    use_fake_client(monkeypatch, reply=None)
    assert complete("hi") == ""

# ---------- LLMSettings validation ----------


@pytest.mark.parametrize("temperature", [0, 0.7, 2])
def test_temperature_in_range_accepted(temperature):
    assert LLMSettings(temperature=temperature).temperature == temperature


@pytest.mark.parametrize("temperature", [-0.1, 2.1, math.nan])
def test_temperature_out_of_range_rejected(temperature):
    with pytest.raises(ValidationError):
        LLMSettings(temperature=temperature)


def test_max_tokens_positive_accepted():
    assert LLMSettings(max_tokens=1).max_tokens == 1


@pytest.mark.parametrize("max_tokens", [0, -5])
def test_max_tokens_non_positive_rejected(max_tokens):
    with pytest.raises(ValidationError):
        LLMSettings(max_tokens=max_tokens)


def test_settings_unknown_field_rejected():
    with pytest.raises(ValidationError, match="temp"):
        LLMSettings(temp=0.5)
