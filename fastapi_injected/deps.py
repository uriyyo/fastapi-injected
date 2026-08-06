import inspect
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, AsyncExitStack, contextmanager
from contextvars import ContextVar, Token
from copy import copy
from functools import lru_cache, wraps
from typing import Annotated, Any, Literal, cast, overload

from fastapi import Depends
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant, get_typed_signature, solve_dependencies

from .scope import InjectScope
from .sign import prepare_sign, update_func_sign
from .types import Coro, HasSignature


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

    cast("HasSignature", _factory).__signature__ = inspect.Signature(
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
async def resolve_dependencies(
    dependant: Dependant,
    scope: InjectScope,
    *,
    single: Literal[False] = False,
) -> dict[str, Any]: ...


@overload
async def resolve_dependencies(
    dependant: Dependant,
    scope: InjectScope,
    *,
    single: Literal[True],
) -> Any: ...


async def resolve_dependencies(
    dependant: Dependant,
    scope: InjectScope,
    *,
    single: bool = False,
) -> dict[str, Any]:
    solved = await solve_dependencies(
        request=scope.request,
        dependant=dependant,
        dependency_cache=copy(scope.dependency_cache),
        dependency_overrides_provider=_dependency_override_provider.get(),
        # this parameter is deprecated and not used
        async_exit_stack=cast(AsyncExitStack, None),
        embed_body_fields=False,
    )

    scope.dependency_cache.update(solved.dependency_cache)

    if solved.errors:
        raise ValueError(solved.errors)

    if single:
        try:
            return solved.values["__value__"]
        except KeyError:
            raise ValueError("No single dependency found") from None

    return solved.values


_dependency_override_provider: ContextVar[Any] = ContextVar(
    "_dependency_override_provider",
    default=None,
)


@contextmanager
def _reset_token(var: ContextVar[Any], token: Token[Any]) -> Iterator[None]:
    try:
        yield
    finally:
        var.reset(token)


def set_inject_dependency_override_provider(provider: Any, /) -> AbstractContextManager[None]:
    token = _dependency_override_provider.set(provider)

    return _reset_token(_dependency_override_provider, token)


def get_inject_dependency_override_provider() -> Any | None:
    return _dependency_override_provider.get()


__all__ = [
    "create_dependant",
    "get_inject_dependency_override_provider",
    "resolve_dependencies",
    "set_inject_dependency_override_provider",
]
