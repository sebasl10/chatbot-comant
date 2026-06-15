from fastapi import HTTPException
from app.config import settings
import httpx
import json

async def call_ollama(prompt: str, system: str = None, stream: bool = False) -> str:
    payload = {
        "model": settings.model_ia,
        "prompt": prompt,
        "stream": False
    }
    if system:
        payload["system"] = system
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            res = await client.post(settings.ollama_url, json=payload)
            res.raise_for_status() # Raises an exception if status code between 400 and 599 (HTTP error)
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Ollama is not running on localhost:11434")
        except httpx.HTTPSStatusError as e:
            raise HTTPException(status_code=502, detail=f"Ollama error: {e.response.text}")
    
    return res.json()["response"]

# Générateur async pour le streaming
async def stream_ollama(prompt: str, system: str = None):
    payload = {
        "model": settings.model_ia,
        "prompt": prompt,
        "stream": True
    }
    if system:
        payload["system"] = system
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", settings.ollama_url, json=payload) as res:
            res.raise_for_status()
            async for line in res.aiter_lines(): # httpx's method allows reading the response line by line as it is received.
                if line:
                    chunk = json.loads(line)
                    yield chunk.get("response", "") # yield is used to send data gradually (streaming).