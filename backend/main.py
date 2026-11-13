from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])

class PromptIn(BaseModel):
    prompt: str

@app.post("/run")
def run(body: PromptIn):
    return {"output": run_prompt(body.prompt)}

@app.get("/health")
def get_health():
    return {"status": "ok"}

@app.get("/")
def main():
    return {"message": "Hello World"}


