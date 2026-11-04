"""Redis-backed fixed-window limiter for authentication endpoints."""
from redis import Redis


_INCREMENT_WITH_EXPIRY = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class AuthRateLimiter:
    def __init__(self, redis_url: str):
        self._redis = Redis.from_url(
            redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            health_check_interval=30,
        )

    def consume(self, key: str, window_seconds: int) -> int:
        return int(self._redis.eval(_INCREMENT_WITH_EXPIRY, 1, key, window_seconds))
