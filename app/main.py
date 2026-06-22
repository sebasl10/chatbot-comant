from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import admin, chat, name
from app.tests.tests import run_intention_tests, run_tests, test_nb_tokens

app = FastAPI(title="LLM API Comant", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],  
)

app.include_router(chat.router)
app.include_router(name.router)
app.include_router(admin.router)

@app.get("/")
def read_root():
    return {"message": "Bienvenue dans ton application FastAPI !"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/tests")
async def tests():
    await run_intention_tests("ollama")
    #await run_tests("ollama")
    
@app.get("/tests/tokens")
async def tests():
    await test_nb_tokens("ollama")