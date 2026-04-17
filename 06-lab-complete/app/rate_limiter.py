import time
from fastapi import HTTPException
from app.config import settings


def _get_redis():
    """Lazy import redis to avoid crash when Redis not configured."""
    try:
        import redis as _redis
        r = _redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def check_rate_limit(user_id: str) -> None:
    """
    Sliding window rate limiter using Redis sorted set.
    Key: rl:{user_id}  Value: sorted set of timestamps
    Raises 429 if exceeded.
    """
    r = _get_redis()
    now = time.time()
    window = 60  # seconds
    limit = settings.rate_limit_per_minute
    key = f"rl:{user_id}"

    if r:
        pipe = r.pipeline()
        # Remove timestamps older than window
        pipe.zremrangebyscore(key, 0, now - window)
        # Count current requests in window
        pipe.zcard(key)
        # Add current request
        pipe.zadd(key, {str(now): now})
        # Reset TTL
        pipe.expire(key, window)
        results = pipe.execute()
        count = results[1]  # count before adding current request
    else:
        # Fallback in-memory (single process only)
        from collections import defaultdict, deque
        if not hasattr(check_rate_limit, "_windows"):
            check_rate_limit._windows = defaultdict(deque)  # type: ignore
        win = check_rate_limit._windows[user_id]  # type: ignore
        while win and win[0] < now - window:
            win.popleft()
        count = len(win)
        win.append(now)

    if count >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} req/min. Try again in 60 seconds.",
            headers={"Retry-After": "60"},
        )
