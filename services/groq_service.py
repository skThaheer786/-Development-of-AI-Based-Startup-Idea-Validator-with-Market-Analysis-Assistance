import json
import re
import time
import logging
import threading
import requests
from config import Config, resolve_model

logger = logging.getLogger(__name__)

class _Limiter:
    """Caps simultaneous Groq calls; Quick mode allows more because its prompts are small."""

    def __init__(self):
        self._cv, self._n = threading.Condition(), 0

    def __enter__(self):
        with self._cv:
            while self._n >= (4 if Config.QUICK_MODE else max(1, Config.LLM_CONCURRENCY)):
                self._cv.wait()
            self._n += 1

    def __exit__(self, *exc):
        with self._cv:
            self._n -= 1
            self._cv.notify()


_LLM_SLOTS = _Limiter()
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(Exception):
    """Raised for any failure talking to the LLM. `kind` lets callers react precisely."""

    FRIENDLY = {
        "bad_key": ("The Groq API key contains characters that are not allowed (usually a placeholder, smart quote or "
                    "extra symbol from copy-paste). Copy the key again from console.groq.com: it starts with gsk_ and "
                    "contains only letters, digits and underscores, with no quotes or spaces."),
        "no_key": "No Groq API key is configured. Add GROQ_API_KEY to your .env file (or in Settings).",
        "auth": "Groq rejected the API key (401/403). Check GROQ_API_KEY.",
        "rate_limit": "Groq rate limit reached. Wait a minute and re-run the analysis.",
        "daily_limit": ("Groq's daily token limit for this account is used up (the free tier allows about 200,000 tokens per day per "
                        "model; one full analysis uses roughly 40,000-60,000). Try again after the reset, use Quick mode, or add billing in the Groq console."),
        "too_large": "The request was larger than Groq's per-minute token limit for this model.",
        "model_unavailable": "The selected Groq model is unavailable or retired. Pick another model in Settings.",
        "bad_request": "Groq rejected the request.",
        "timeout": "Groq did not answer in time.",
        "network": "Could not reach the Groq API (network or DNS problem). Check your internet connection and firewall.",
        "server": "Groq returned a server error.",
        "invalid_json": "The model returned an answer that could not be parsed as JSON.",
        "empty": "The model returned an empty answer (token limit reached).",
    }

    def __init__(self, kind, message=None, status=None, retry_after=None, info=None):
        self.info = info or {}
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        self.detail = message or ""
        super().__init__(self.user_message)

    @property
    def user_message(self):
        base = self.FRIENDLY.get(self.kind, "LLM request failed.")
        if self.detail and self.kind in ("bad_request", "server", "invalid_json", "model_unavailable", "daily_limit", "too_large"):
            return f"{base} ({self.detail[:160]})"
        return base


def parse_json_response(text):
    """Parse a JSON object from model output, tolerating fences, prose and trailing commas."""
    if text is None:
        raise LLMError("invalid_json", "empty response")
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        raise LLMError("invalid_json", "no JSON object found")

    # Walk to find the matching closing brace (string aware)
    depth, in_str, esc, end = 0, False, False, -1
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    snippet = cleaned[start:end + 1] if end != -1 else cleaned[start:]
    snippet = re.sub(r",\s*([}\]])", r"\1", snippet)  # trailing commas
    try:
        return json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise LLMError("invalid_json", str(exc))


def clean_key(key):
    """Trim whitespace and wrapping quotes pasted along with an API key."""
    return (key or "").strip().strip("\"'`").strip()


def key_problem(key):
    """Returns a message when a key cannot possibly be valid, else ''."""
    k = clean_key(key)
    if not k:
        return ""
    if not k.isascii() or any(c.isspace() for c in k):
        return LLMError.FRIENDLY["bad_key"]
    return ""

# ---------------------------------------------------------------------------
# Token budget handling (Groq limits tokens per minute and per day, per model)
# ---------------------------------------------------------------------------
def parse_duration(text):
    """'6m50.832s' -> 410.8, '7.66s' -> 7.66, '820ms' -> 0.82, '1h2m3s' -> 3723. None if no duration found."""
    total, found = 0.0, False
    for val, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(ms|h|m|s)", text or ""):
        found = True
        v = float(val)
        total += v / 1000 if unit == "ms" else v * 3600 if unit == "h" else v * 60 if unit == "m" else v
    return total if found else None


def parse_rate_message(msg):
    """Reads Groq's own wording: scope (tpm/tpd/rpm/rpd), Limit, Used, Requested and 'try again in ...'."""
    m = msg or ""
    scope = None
    for pat, name in ((r"tokens per day|\(TPD\)", "tpd"), (r"tokens per minute|\(TPM\)", "tpm"),
                      (r"requests per day|\(RPD\)", "rpd"), (r"requests per minute|\(RPM\)", "rpm")):
        if re.search(pat, m, re.I):
            scope = name
            break
    num = lambda key: (int(re.search(rf"{key}\s+(\d+)", m).group(1)) if re.search(rf"{key}\s+(\d+)", m) else None)
    idx = m.lower().find("try again in")
    return {"scope": scope, "limit": num("Limit"), "used": num("Used"), "requested": num("Requested"),
            "wait": parse_duration(m[idx:]) if idx >= 0 else None}


def fmt_wait(seconds):
    seconds = int(max(0, seconds))
    if seconds >= 3600:
        return f"{seconds // 3600} h {(seconds % 3600) // 60} min"
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"


class TokenPacer:
    """
    Shared (all threads, all agents) record of tokens sent to each model during the last 60 seconds.
    It delays a request that would exceed the model's per-minute budget, learns the real limit from Groq's own error
    messages, and remembers models whose DAILY budget is exhausted so they are skipped instead of retried.
    """
    WINDOW = 60.0

    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._events, self._learned, self._blocked, self._next = {}, {}, {}, 0

    def limit_for(self, model):
        if int(Config.GROQ_TPM_LIMIT or 0) <= 0:
            return 0
        return self._learned.get(model) or int(Config.GROQ_TPM_LIMIT)

    def learn(self, model, limit):
        if limit and int(limit) >= 1000:
            self._learned[model] = int(limit)

    def block(self, model, seconds):
        self._blocked[model] = self._clock() + max(1.0, float(seconds))

    def blocked_for(self, model):
        return max(0.0, self._blocked.get(model, 0) - self._clock())

    def reset(self):
        with self._lock:
            self._events.clear(); self._learned.clear(); self._blocked.clear()

    def _live(self, model, now):
        events = [e for e in self._events.get(model, []) if now - e[0] < self.WINDOW]
        self._events[model] = events
        return events

    def wait_needed(self, model, est):
        limit = self.limit_for(model)
        if not limit:
            return 0.0
        with self._lock:
            now = self._clock()
            events = self._live(model, now)
            cap = limit * 0.97
            need = sum(e[1] for e in events) + est - cap
            if need <= 0:
                return 0.0
            freed = 0
            for ts, tok, _ in sorted(events):
                freed += tok
                if freed >= need:
                    return max(0.5, ts + self.WINDOW - now)
            return self.WINDOW

    def reserve(self, model, est):
        with self._lock:
            self._next += 1
            self._events.setdefault(model, []).append([self._clock(), est, self._next])
            return (model, self._next)

    def settle(self, handle, actual):
        with self._lock:
            for e in self._events.get(handle[0], []):
                if e[2] == handle[1]:
                    e[1] = max(1, int(actual))

    def release(self, handle):
        with self._lock:
            self._events[handle[0]] = [e for e in self._events.get(handle[0], []) if e[2] != handle[1]]


_PACER = TokenPacer()


class GroqService:
    """Groq chat-completions client with retries, model fallback and clear errors."""

    def __init__(self, api_key=None, model=None, fallback_model=None, sleep=time.sleep):
        self.api_key = clean_key(api_key or Config.GROQ_API_KEY)
        self.model, _ = resolve_model(model or Config.GROQ_MODEL)
        self.fallback_model, _ = resolve_model(fallback_model or Config.GROQ_FALLBACK_MODEL)
        self._sleep = sleep
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
        self.last_model_used = None

    # ------------------------------------------------------------------
    def is_available(self):
        return bool(self.api_key and len(self.api_key) > 10)

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _is_reasoning_model(model):
        return model.startswith("openai/gpt-oss")

    def _payload(self, model, messages, temperature, max_tokens, json_mode):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self._is_reasoning_model(model):
            payload["reasoning_effort"] = "low"
            payload["include_reasoning"] = False
        return payload

    # ------------------------------------------------------------------
    def test_connection(self):
        """Test Groq connectivity. Returns (success, message)."""
        if not self.is_available():
            return False, LLMError.FRIENDLY["no_key"]
        if key_problem(self.api_key):
            return False, LLMError.FRIENDLY["bad_key"]
        try:
            text = self.chat_completion(
                [{"role": "user", "content": "Reply with the single word OK."}],
                temperature=0.0, max_tokens=64, retries=1,
            )
            note = ""
            if self.last_model_used and self.last_model_used != self.model:
                note = f" (fell back to {self.last_model_used})"
            return True, f"Groq connected using {self.last_model_used}{note}. Response: {str(text).strip()[:40]}"
        except LLMError as exc:
            return False, exc.user_message

    # ------------------------------------------------------------------
    def _single_request(self, payload):
        """One HTTP request. Returns parsed response dict or raises LLMError."""
        try:
            with _LLM_SLOTS:
                resp = requests.post(GROQ_CHAT_URL, headers=self._headers(), json=payload,
                                     timeout=Config.LLM_TIMEOUT)
        except requests.exceptions.Timeout:
            raise LLMError("timeout")
        except UnicodeEncodeError:
            raise LLMError("bad_key")
        except requests.exceptions.RequestException as exc:
            raise LLMError("network", str(exc))

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                raise LLMError("server", "non-JSON body from Groq", status=200)

        # Error response -> classify
        try:
            err = resp.json().get("error", {})
        except Exception:
            err = {}
        code = (err.get("code") or "").lower()
        msg = err.get("message") or resp.text[:200]
        retry_after = None
        try:
            retry_after = float(resp.headers.get("retry-after"))
        except (TypeError, ValueError):
            pass

        if resp.status_code in (401, 403):
            raise LLMError("auth", msg, status=resp.status_code)
        info = parse_rate_message(msg)
        if resp.status_code == 413 or (info["scope"] == "tpm" and "request too large" in msg.lower()):
            raise LLMError("too_large", msg, status=413, info=info)
        if resp.status_code == 429:
            raise LLMError("rate_limit", msg, status=429, retry_after=retry_after, info=info)
        lowered = msg.lower()
        if "model" in code or resp.status_code == 404 or "decommission" in lowered \
                or "model_not_found" in lowered or "does not exist" in lowered:
            raise LLMError("model_unavailable", msg, status=resp.status_code)
        if resp.status_code == 400:
            if "json_validate_failed" in code or "json" in lowered:
                raise LLMError("invalid_json", msg, status=400)
            raise LLMError("bad_request", msg, status=400)
        if resp.status_code >= 500:
            raise LLMError("server", msg, status=resp.status_code)
        raise LLMError("bad_request", msg, status=resp.status_code)

    @staticmethod
    def _estimate_tokens(messages):
        return int(sum(len(str(m.get("content", ""))) for m in messages) / 3.3) + 20

    @staticmethod
    def _shrink(messages, budget_tokens):
        """Last resort when the prompt alone cannot fit the per-minute limit: trim the middle of the longest message."""
        msgs = [dict(m) for m in messages]
        idx = max(range(len(msgs)), key=lambda i: len(str(msgs[i].get("content", ""))))
        others = sum(len(str(m.get("content", ""))) for i, m in enumerate(msgs) if i != idx)
        allowed = max(3000, int(budget_tokens * 3.3) - others)
        text = str(msgs[idx].get("content", ""))
        if len(text) <= allowed:
            return msgs
        head, tail = int(allowed * 0.4), int(allowed * 0.55)
        msgs[idx]["content"] = (text[:head] + "\n[... some supporting evidence was trimmed to fit the model's per-minute token limit ...]\n"
                                + text[-tail:])
        return msgs

    def _acquire(self, model, est):
        """Wait (briefly, in small steps) until the model has room in its per-minute budget, then reserve it."""
        waited = 0.0
        while waited < 90:
            wait = _PACER.wait_needed(model, est)
            if wait <= 0:
                break
            step = min(max(wait, 0.5), 3.0)
            self._sleep(step)
            waited += step
        return _PACER.reserve(model, est)

    def chat_completion(self, messages, temperature=0.7, max_tokens=2048, json_mode=False, retries=3, fast=False):
        """
        Execute a chat completion.
        Returns a dict when json_mode=True, otherwise the response text.
        Raises LLMError (never returns fabricated content).

        Token limits are handled here: the requested output is clamped so input + output fits the model's per-minute
        budget, requests are paced across all agents, a 'request too large' error shrinks the request and retries,
        and a model whose daily budget is exhausted is skipped in favour of the other one.
        """
        if not self.is_available():
            raise LLMError("no_key")
        if key_problem(self.api_key):
            raise LLMError("bad_key")

        models = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            models = [self.fallback_model, self.model] if fast else models + [self.fallback_model]
        live = [m for m in models if _PACER.blocked_for(m) <= 0]
        if not live:
            raise LLMError("daily_limit", f"resets in about {fmt_wait(min(_PACER.blocked_for(m) for m in models))}")
        est_in0 = self._estimate_tokens(messages)
        live.sort(key=lambda m: _PACER.wait_needed(m, est_in0 + min(max_tokens, 3000)) > 0)   # a model with free capacity first

        last_error = None
        for model in live:
            use_json_mode = json_mode
            wanted = max_tokens
            msgs = messages
            attempt = 0
            while attempt < retries:
                attempt += 1
                limit = _PACER.limit_for(model)
                tokens = wanted
                if limit:
                    budget = int(limit * 0.97)
                    if budget - self._estimate_tokens(msgs) < 900:
                        msgs = self._shrink(msgs, budget - 900)
                    tokens = max(400, min(wanted, budget - self._estimate_tokens(msgs)))
                handle = self._acquire(model, self._estimate_tokens(msgs) + tokens)
                try:
                    data = self._single_request(self._payload(model, msgs, temperature, tokens, use_json_mode))
                    choice = (data.get("choices") or [{}])[0]
                    content = (choice.get("message") or {}).get("content") or ""
                    usage = data.get("usage") or {}
                    if usage.get("total_tokens") or usage.get("prompt_tokens"):
                        _PACER.settle(handle, usage.get("total_tokens") or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)))
                    self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                    self.usage["completion_tokens"] += usage.get("completion_tokens", 0)
                    self.usage["calls"] += 1
                    self.last_model_used = model

                    if not content.strip():
                        last_error = LLMError("empty")
                        if choice.get("finish_reason") == "length" and wanted < 12000:
                            wanted = int(wanted * 1.4)   # reasoning consumed the budget (clamped to the limit above)
                        continue

                    if json_mode:
                        try:
                            return parse_json_response(content)
                        except LLMError as exc:
                            last_error = exc
                            if choice.get("finish_reason") == "length" and wanted < 12000:
                                wanted = int(wanted * 1.4)
                            continue
                    return content

                except LLMError as exc:
                    last_error = exc
                    _PACER.release(handle)
                    logger.warning("Groq %s attempt %d failed: %s %s", model, attempt, exc.kind, (exc.detail or "")[:140])
                    if exc.kind in ("auth", "no_key", "bad_key"):
                        raise
                    if exc.kind == "model_unavailable":
                        break  # try fallback model
                    if exc.kind == "invalid_json" and exc.status == 400 and use_json_mode:
                        use_json_mode = False  # server-side JSON validation failed; parse manually
                        continue
                    if exc.kind == "too_large":
                        info = exc.info or {}
                        _PACER.learn(model, info.get("limit"))
                        over = (info.get("requested") or 0) - (info.get("limit") or 0)
                        if tokens > 900:
                            wanted = max(700, tokens - max(over, 0) - 250) if over > 0 else int(tokens * 0.7)
                        else:
                            msgs = self._shrink(msgs, int((info.get("limit") or Config.GROQ_TPM_LIMIT or 8000) * 0.97) - 900)
                        continue
                    if exc.kind == "rate_limit":
                        info = exc.info or {}
                        if info.get("scope") in ("tpd", "rpd"):
                            _PACER.block(model, info.get("wait") or 3600)     # daily budget gone: use the other model
                            break
                        if info.get("scope") == "tpm":
                            _PACER.learn(model, info.get("limit"))
                        if attempt >= retries:
                            break
                        wait = info.get("wait") or exc.retry_after or 5 * attempt
                        self._sleep(min(wait + 0.5, 65))                      # Groq's window is 60 s
                        continue
                    if exc.kind in ("server", "timeout", "network"):
                        if attempt >= retries:
                            break
                        self._sleep(2 * attempt)
                        continue
                    raise  # bad_request etc.
            # attempts for this model exhausted -> loop to the other model

        if all(_PACER.blocked_for(m) > 0 for m in models):
            raise LLMError("daily_limit", f"resets in about {fmt_wait(min(_PACER.blocked_for(m) for m in models))}")
        raise last_error or LLMError("server", "unknown failure")
