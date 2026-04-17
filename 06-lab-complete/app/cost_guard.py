import time
from fastapi import HTTPException
from app.config import settings

PRICE_PER_1K_INPUT = 0.00015   # GPT-4o-mini input
PRICE_PER_1K_OUTPUT = 0.0006   # GPT-4o-mini output


def _get_redis():
    try:
        import redis as _redis
        r = _redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _month_key(user_id: str) -> str:
    month = time.strftime("%Y-%m")
    return f"budget:{month}:{user_id}"


def check_budget(user_id: str) -> None:
    """
    Check monthly budget per user.
    Raises 402 if user has exceeded MONTHLY_BUDGET_USD.
    """
    r = _get_redis()
    key = _month_key(user_id)
    budget = settings.monthly_budget_usd

    if r:
        current = float(r.get(key) or 0.0)
    else:
        if not hasattr(check_budget, "_store"):
            check_budget._store = {}  # type: ignore
        current = check_budget._store.get(key, 0.0)  # type: ignore

    if current >= budget:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "used_usd": round(current, 4),
                "budget_usd": budget,
                "resets_at": "1st of next month",
            },
        )


def record_usage(user_id: str, input_tokens: int, output_tokens: int) -> float:
    """
    Record token usage and return updated total cost this month.
    """
    cost = (input_tokens / 1000) * PRICE_PER_1K_INPUT + \
           (output_tokens / 1000) * PRICE_PER_1K_OUTPUT
    r = _get_redis()
    key = _month_key(user_id)

    if r:
        new_total = r.incrbyfloat(key, cost)
        # Expire key after 35 days (covers full month)
        r.expire(key, 60 * 60 * 24 * 35)
    else:
        if not hasattr(check_budget, "_store"):
            check_budget._store = {}  # type: ignore
        check_budget._store[key] = check_budget._store.get(key, 0.0) + cost  # type: ignore
        new_total = check_budget._store[key]  # type: ignore

    return round(new_total, 6)
