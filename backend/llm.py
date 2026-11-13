from openai import OpenAI
from pydantic import BaseModel
import config


client = OpenAI(base_url=config.OPENAI_BASE_URL, api_key=config.OPENAI_API_KEY)

class LLMSettings(BaseModel):
    model: str = config.LLM_MODEL
    temperature: float = 0.7
    max_tokens: int | None = None
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
    
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""

def fake_complete(prompt: str, settings: LLMSettings | None = None) -> str:
    return f"Fake response to prompt: {prompt}"