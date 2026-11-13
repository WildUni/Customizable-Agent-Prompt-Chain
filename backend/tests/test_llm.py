from types import SimpleNamespace

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