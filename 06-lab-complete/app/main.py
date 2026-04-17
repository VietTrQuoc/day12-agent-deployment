"""Production AI Agent app entrypoint."""
import json
import logging
import signal
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_usage
from app.rate_limiter import check_rate_limit
from utils.mock_llm import ask as llm_ask

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_request_count = 0
_error_count = 0


def _get_redis():
    try:
        import redis as _redis

        r = _redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _save_history(session_id: str, role: str, content: str):
    r = _get_redis()
    if not r:
        return
    key = f"history:{session_id}"
    entry = json.dumps(
        {"role": role, "content": content, "ts": datetime.now(timezone.utc).isoformat()}
    )
    r.rpush(key, entry)
    r.ltrim(key, -20, -1)
    r.expire(key, 3600)


def _load_history(session_id: str) -> list:
    r = _get_redis()
    if not r:
        return []
    raw = r.lrange(f"history:{session_id}", 0, -1)
    return [json.loads(m) for m in raw]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    logger.info(
        json.dumps(
            {
                "event": "startup",
                "app": settings.app_name,
                "version": settings.app_version,
                "environment": settings.environment,
            }
        )
    )
    time.sleep(0.1)
    _is_ready = True
    logger.info(json.dumps({"event": "ready"}))
    yield
    _is_ready = False
    logger.info(json.dumps({"event": "shutdown"}))


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _request_count, _error_count
    start = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if "server" in response.headers:
            del response.headers["server"]
        duration = round((time.time() - start) * 1000, 1)
        logger.info(
            json.dumps(
                {
                    "event": "request",
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": duration,
                }
            )
        )
        return response
    except Exception:
        _error_count += 1
        raise


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None


class AskResponse(BaseModel):
    session_id: str
    question: str
    answer: str
    model: str
    turn: int
    timestamp: str


@app.get("/", tags=["Info"])
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "endpoints": {
            "ask": "POST /ask (requires X-API-Key)",
            "health": "GET /health",
            "ready": "GET /ready",
        },
    }


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(body: AskRequest, request: Request, user_id: str = Depends(verify_api_key)):
    check_rate_limit(user_id)
    check_budget(user_id)

    session_id = body.session_id or str(uuid.uuid4())
    history = _load_history(session_id)
    turn = len([m for m in history if m["role"] == "user"]) + 1

    _save_history(session_id, "user", body.question)

    logger.info(
        json.dumps(
            {
                "event": "agent_call",
                "user": user_id,
                "session": session_id,
                "turn": turn,
                "client": str(request.client.host) if request.client else "unknown",
            }
        )
    )

    answer = llm_ask(body.question)
    _save_history(session_id, "assistant", answer)

    input_tokens = len(body.question.split()) * 2
    output_tokens = len(answer.split()) * 2
    record_usage(user_id, input_tokens, output_tokens)

    return AskResponse(
        session_id=session_id,
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        turn=turn,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/health", tags=["Operations"])
def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    if not _is_ready:
        raise HTTPException(503, "Agent not ready yet")
    r = _get_redis()
    if settings.redis_url and not r:
        raise HTTPException(503, "Redis not reachable")
    return {"ready": True, "redis": "ok" if r else "not configured"}


@app.get("/metrics", tags=["Operations"])
def metrics(_: str = Depends(verify_api_key)):
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "error_count": _error_count,
    }


def _handle_signal(signum, _frame):
    logger.info(json.dumps({"event": "signal", "signum": signum}))


signal.signal(signal.SIGTERM, _handle_signal)


if __name__ == "__main__":
    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
