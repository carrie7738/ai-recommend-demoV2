"""Request-local debug snapshots; never used as model or business input."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from time import perf_counter
from uuid import uuid4
import re

_active = ContextVar("procurement_trace", default=None)
_model_stage = ContextVar("procurement_model_stage", default="decision")
_SECRET = re.compile(r"api[_-]?key|authorization|password|secret|private[_-]?key|access[_-]?token|refresh[_-]?token|(?:^|[_-])token$|cookie|credential", re.I)
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
    re.I | re.S,
)
_SNAPSHOT_UNAVAILABLE = "[REDACTED: snapshot unavailable]"
_ERROR_UNAVAILABLE = "[REDACTED: error unavailable]"

def snapshot(value):
    """Return a safe snapshot without allowing observation to affect business code."""
    try:
        return _snapshot(value)
    except Exception:
        return _SNAPSHOT_UNAVAILABLE


def _snapshot(value):
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if _SECRET.search(str(k)) else snapshot(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [snapshot(v) for v in value]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        import math
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        value = _PEM_PRIVATE_KEY.sub("[REDACTED]", value)
        value = re.sub(r"(?i)(Bearer|Basic)\s+[^\s\"']+", r"\1 [REDACTED]", value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
        return re.sub(
            r"(?i)((?:api[_-]?key|authorization|password|secret|private[_-]?key|access[_-]?token|token|cookie|credential)[\"']?\s*[:=]\s*[\"']?)([^\"'\s,;}]+)",
            r"\1[REDACTED]", value,
        )
    if hasattr(value, "to_dict"):
        return snapshot(value.to_dict())
    return snapshot(str(value))


def _safe_error(exc):
    try:
        return str(exc)
    except Exception:
        return _ERROR_UNAVAILABLE

@contextmanager
def capture_trace(existing=None):
    trace = existing if existing is not None else {"run_id": str(uuid4()), "started_at": datetime.now(timezone.utc).isoformat(), "events": [], "metadata": {}}
    token = _active.set(trace)
    try:
        yield trace
    finally:
        _active.reset(token)

def record(stage, owner, input=None, output=None, status="success", **extra):
    trace = _active.get()
    if trace is None:
        return
    trace["events"].append(snapshot({"sequence": len(trace["events"])+1, "recorded_at": datetime.now(timezone.utc).isoformat(), "stage": stage, "owner": owner, "status": status, "input": input, "output": output, **extra}))

def is_capturing():
    return _active.get() is not None

def model_stage():
    return _model_stage.get()

def observed(stage, owner):
    """Capture outputs/errors without changing function arguments or return values."""
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if _active.get() is None:
                return fn(*args, **kwargs)
            started = perf_counter()
            captured_input = None
            token = _model_stage.set("intent" if stage == "intent_output" else "decision")
            try:
                if stage == "validation":
                    from inspect import signature
                    bound = signature(fn).bind(*args, **kwargs).arguments
                    captured_input = {k: bound[k] for k in ("optimizer_result", "violations", "structured_intent") if k in bound}
                    captured_input = snapshot(captured_input)
                result = fn(*args, **kwargs)
                status = "success"
                if isinstance(result, dict):
                    if result.get("AIAnalysisStatus") == "fallback": status = "fallback"
                    if result.get("valid") is False or result.get("v2_status") == "FAILED": status = "failed"
                record(stage, owner, input=captured_input, output=result, status=status, operation=fn.__name__, duration_ms=round((perf_counter()-started)*1000, 2))
                return result
            except Exception as exc:
                record(stage, owner, input=captured_input, status="failed", operation=fn.__name__, error=_safe_error(exc), duration_ms=round((perf_counter()-started)*1000, 2))
                raise
            finally:
                _model_stage.reset(token)
        return wrapped
    return decorate
