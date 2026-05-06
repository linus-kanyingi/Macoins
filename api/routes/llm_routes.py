"""api/routes/llm_routes.py — LLM provider/model info endpoints."""
from fastapi import APIRouter
from agents.llm_router import get_available_providers, list_ollama_models, is_ollama_available

router = APIRouter()


@router.get("/api/llm/providers")
def get_providers():
    """List available LLM providers with their models."""
    return {"providers": get_available_providers()}


@router.get("/api/llm/ollama/models")
def get_ollama_models():
    """List locally available Ollama models."""
    return {"models": list_ollama_models()}


@router.get("/api/llm/status")
def get_status():
    """Check overall LLM availability."""
    providers = get_available_providers()
    available_count = sum(1 for p in providers if p["available"])
    return {
        "providers": providers,
        "available_count": available_count,
        "ollama_running": is_ollama_available(),
    }
