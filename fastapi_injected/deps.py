import inspect
from contextvars import ContextVar
from copy import copy
from functools import lru_cache, wraps
from typing import Annotated, Any, Callable, Literal, cast, overload

from fastapi import Depends
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant, get_typed_signature
from fastapi.dependencies.utils import solve_dependencies as _solve_dependencies
from starlette.requests import Request
from starlette.types import Message, Scope

from .scope import InjectScope
from .sign import prepare_sign, update_func_sign
from .types import Coro, HasSignature


def _dummy_scope() -> Scope:
    return {
        "type": "http",
        "http_version": "1.1",
        "query_string": b"",
        "headers": [],
    }


def _dummy_request(
    *,
    extra_scope: Scope | None = None,
) -> Request:
    async def _dummy_receive() -> Message:
        return {
            "type": "http.request",
            "body": b"",
        }

    async def _dummy_send(_: Message, /) -> None:
        pass

    scope = _dummy_scope()
    if extra_scope:
        scope.update(extra_scope)

    return Request(
        scope,
        receive=_dummy_receive,
        send=_dummy_send,
    )


@lru_cache(maxsize=1024)
def create_dependant[**P, R](func: Callable[P, Coro[R]], /) -> Dependant:
    @wraps(func)
    async def __call(*args: P.args, **kwargs: P.kwargs) -> R:
        return await func(*args, **kwargs)

    update_func_sign(
        __call,
        prepare_sign(get_typed_signature(func)),
    )

    return get_dependant(
        path="",
        call=__call,
    )


@lru_cache(maxsize=1024)
def create_single_dependant[**P, R](func: Callable[P, R], /) -> Dependant:
    async def _factory(__value__: R) -> R:
        return __value__

    cast(HasSignature, _factory).__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter(
                "__value__",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Annotated[Any, Depends(func)],
            ),
        ],
        return_annotation=Any,
    )

    return get_dependant(
        path="",
        call=_factory,
    )


@overload
async def solve_dependencies(
    dependant: Dependant,
    scope: InjectScope,
    *,
    single: Literal[False] = False,
) -> dict[str, Any]: ...


@overload
async def solve_dependencies(
    dependant: Dependant,
    scope: InjectScope,
    *,
    single: Literal[True],
) -> Any: ...


async def solve_dependencies(
    dependant: Dependant,
    scope: InjectScope,
    *,
    single: bool = False,
) -> dict[str, Any]:
    solved = await _solve_dependencies(
        request=_dummy_request(
            extra_scope={
                "fastapi_inner_astack": scope.request_astack,
                "fastapi_function_astack": scope.func_astack,
            }
        ),
        dependant=dependant,
        async_exit_stack=scope.request_astack,
        dependency_cache=copy(scope.dependency_cache),
        dependency_overrides_provider=_dependency_override_provider.get(),
        embed_body_fields=False,
    )

    scope.dependency_cache.update(solved.dependency_cache)

    if single:
        try:
            return solved.values["__value__"]
        except KeyError:
            raise ValueError("No single dependency found")

    return solved.values


_dependency_override_provider: ContextVar[Any] = ContextVar(
    "_dependency_override_provider",
    default=None,
)


def set_inject_dependency_override_provider(provider: Any, /) -> None:
    _dependency_override_provider.set(provider)


__all__ = [
    "set_inject_dependency_override_provider",
    "create_dependant",
    "solve_dependencies",
]
