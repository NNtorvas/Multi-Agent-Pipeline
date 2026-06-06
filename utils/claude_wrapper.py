import os
import time
import logging
import functools
from pathlib import Path

from anthropic import Anthropic

MODEL = "claude-sonnet-4-20250514"
_TOKEN_LOG = Path(__file__).parent.parent / "logs" / "token_usage.log"
_TOKEN_LOG.parent.mkdir(exist_ok=True)

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def retry(max_retries: int = 3, base_delay: float = 1.0):
    """Exponential-backoff retry decorator shared by data fetch and Claude calls."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    logging.warning(
                        "[retry] %s attempt %d/%d failed: %s — retrying in %.1fs",
                        func.__name__, attempt + 1, max_retries, exc, delay,
                    )
                    time.sleep(delay)
        return wrapper
    return decorator


@retry(max_retries=3)
def call_claude(
    messages: list[dict],
    system: str = "",
    max_tokens: int = 1024,
) -> str:
    """Single entry point for all Claude API calls. Logs token usage to file."""
    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    _log_tokens(response.usage)
    return response.content[0].text


def _log_tokens(usage) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(_TOKEN_LOG, "a") as f:
        f.write(f"{ts} | input={usage.input_tokens} | output={usage.output_tokens}\n")
