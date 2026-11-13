from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

import config

# Created on first real call (see get_client), so importing this module never
# needs an API key. That keeps tests and USE_FAKE_LLM mode working without .env.
client: OpenAI | None = None


def get_client() -> OpenAI:
    global client
    if client is None:
        if not config.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to backend/.env "
                "(see .env.example), or set USE_FAKE_LLM=true."
            )
        client = OpenAI(base_url=config.OPENAI_BASE_URL, api_key=config.OPENAI_API_KEY)
    return client


class LLMSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = config.LLM_MODEL
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    system: str | None = None

def complete(prompt: str, settings: LLMSettings | None = None) -> str:
    s = settings or LLMSettings()
    if config.USE_FAKE_LLM:
        return fake_complete(prompt, settings)
    
    messages = []
    if s.system:
        messages.append({"role": "system", "content": s.system})
    messages.append({"role": "user", "content": prompt})

    kwargs = {"model": s.model, "messages": messages, "temperature": s.temperature}
    if s.max_tokens is not None:
        kwargs["max_tokens"] = s.max_tokens
    
    resp = get_client().chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""

def fake_complete(prompt: str, settings: LLMSettings | None = None) -> str:
    return f"Fake response to prompt: {prompt}"