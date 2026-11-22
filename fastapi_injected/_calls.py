import inspect
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any

from fastapi.params import Depends

from ._deps_tp import annotated_parts
from ._fastapi_compat import patch_call_classifiers
from .ctx import set_var

_RUNTIME_CALLS: ContextVar[bool] = ContextVar(
    "fastapi_injected_runtime_calls",
    default=False,
)


def _is_static_call(call: Any, /) -> bool:
    # what source code wrote down lives as long as the process anyway, so caching
    # by it keeps nothing extra alive - an instance or a closure may carry request data
    if inspect.isclass(call):
        return True

    # a builtin bound to an instance, like `cache.get`, carries that instance along
    if inspect.isbuiltin(call):
        return call.__self__ is None or inspect.ismodule(call.__self__)

    # `__qualname__` is what `functools.wraps` copied over, the code knows where it was defined
    if inspect.isfunction(call):
        return "<locals>" not in call.__code__.co_qualname

    return False


def is_static_annotation(annotation: Any, /) -> bool:
    match annotated_parts(annotation):
        case (tp, metadata):
            return all(
                _is_static_call(tp if meta.dependency is None else meta.dependency)
                for meta in metadata
                if isinstance(meta, Depends)
            )
        case _:
            return False


def _skip_cache_for_runtime_calls(cached: Callable[[Any], bool], /) -> Callable[[Any], bool]:
    @wraps(cached)
    def classify(identity: Any, /) -> bool:
        if _RUNTIME_CALLS.get() and not _is_static_call(identity.call):
            return cached.__wrapped__(identity)  # type: ignore[ty:missing-attribute]

        return cached(identity)

    classify.cache_clear = cached.cache_clear  # type: ignore[ty:missing-attribute]
    classify.cache_info = cached.cache_info  # type: ignore[ty:missing-attribute]

    return classify


patch_call_classifiers(_skip_cache_for_runtime_calls)


@contextmanager
def runtime_calls() -> Generator[bool, Any, Any]:
    # FastAPI caches every call it classifies, so a call made at runtime is classified uncached
    with set_var(_RUNTIME_CALLS, True):
        yield True


__all__ = [
    "is_static_annotation",
    "runtime_calls",
]
