import inspect
from collections.abc import Callable
from contextlib import AsyncExitStack
from functools import lru_cache, wraps
from typing import Annotated, Any, Literal, Protocol, cast, overload, runtime_checkable

from fastapi import Depends, params
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant, get_typed_signature, solve_dependencies
from fastapi.exceptions import RequestValidationError

from ._deps_tp import is_dep, unwrap_tp
from .scope import InjectScope
from .sign import prepare_sign, update_func_sign
from .types import Coro, DependencyCache, HasSignature


class DependencyResolutionError(ValueError):
    def __init__(self, errors: list[Any], /) -> None:
        super().__init__(errors)
        self.errors = errors

    def as_validation_error(self) -> RequestValidationError:
        return RequestValidationError(self.errors)


class MissedDependencyError(ValueError):
    def __init__(self, name: str, /) -> None:
        super().__init__(f"dependency {name!r} is not available")
        self.name = name


@runtime_checkable
class HasDependsHook[**P, R](Protocol):
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        pass

    def __get_depends__(self) -> params.Depends:
        pass


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


def create_single_dependant[**P, R](
    func: Callable[P, R] | HasDependsHook[P, R],
    /,
    *,
    path: str | None = None,
) -> Dependant:
    match func:
        case _ if is_dep(func):
            annotation = unwrap_tp(func)
        case HasDependsHook():
            annotation = Annotated[Any, func.__get_depends__()]
        case _:
            annotation = Annotated[Any, Depends(func)]

    return _create_annotation_dependant(annotation, path=path)


@lru_cache(maxsize=1024)
def _create_annotation_dependant(annotation: Any, /, *, path: str | None = None) -> Dependant:
    async def _factory(__value__: Any) -> Any:
        return __value__

    cast("HasSignature", _factory).__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter(
                "__value__",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=annotation,
            ),
        ],
        return_annotation=Any,
    )

    return get_dependant(
        path=path or "",
        call=_factory,
    )


def clear_dependant_cache() -> None:
    _create_annotation_dependant.cache_clear()


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
    async with scope.lock:
        solved = await solve_dependencies(
            request=scope.bound_request,
            dependant=dependant,
            dependency_cache=cast("DependencyCache", scope.cache_for(dependant)),
            dependency_overrides_provider=scope,
            # this parameter is deprecated and not used
            async_exit_stack=cast(AsyncExitStack, None),
            embed_body_fields=False,
        )

    if solved.errors:
        raise DependencyResolutionError(solved.errors)

    if single:
        try:
            return solved.values["__value__"]
        except KeyError:
            raise MissedDependencyError("__value__") from None

    return solved.values


__all__ = [
    "DependencyResolutionError",
    "MissedDependencyError",
    "clear_dependant_cache",
    "create_dependant",
    "resolve_dependencies",
]
