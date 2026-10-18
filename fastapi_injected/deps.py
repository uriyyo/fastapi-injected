import inspect
from collections.abc import Callable, Generator
from contextlib import AsyncExitStack, contextmanager
from functools import lru_cache
from typing import Any, cast, get_args

from fastapi import Depends, params
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant, solve_dependencies
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

from ._body import InvalidBodyError, request_body
from ._calls import CallProxy, DetachedOverrides, annotated, is_static_annotation, release
from ._deps_tp import is_dep, is_request_param, unwrap_tp
from .ctx import InjectionContext
from .signature import Signature
from .types import Coro, DependencyCache, HasDependsHook, HasSignature


class DependencyResolutionError(ValueError):
    def __init__(self, errors: list[Any], /) -> None:
        super().__init__(errors)
        self.errors = errors

    def as_validation_error(self) -> RequestValidationError:
        return RequestValidationError(self.errors)


class UnnamedParamError(TypeError):
    def __init__(self, param: Any, /) -> None:
        super().__init__(
            f"{type(param).__name__}() resolved on its own has no parameter name to read from the request - "
            f"give it an alias, like {type(param).__name__}(alias='x-api-key')",
        )

        self.param = param


class MissedDependencyError(ValueError):
    def __init__(self, name: str, /) -> None:
        super().__init__(f"dependency {name!r} is not available")
        self.name = name


def create_dependant[**P, R](func: Callable[P, Coro[R]], /) -> Dependant:
    return get_dependant(
        path="",
        call=Signature.of(func).prepare().wrap(func),
    )


@contextmanager
def open_dependant[**P, R](
    tp: Callable[P, R] | HasDependsHook[P, R],
    /,
    *,
    path: str | None = None,
) -> Generator[Dependant]:
    match tp:
        case _ if is_dep(tp):
            annotation = unwrap_tp(tp)
        case _ if is_request_param(tp):
            annotation = _named_param(unwrap_tp(tp))
        case params.Param() | params.Body():
            annotation = _named_param(annotated(Any, tp))
        case HasDependsHook():
            annotation = annotated(Any, tp.__get_depends__())
        case _:
            annotation = annotated(Any, Depends(tp))

    if is_static_annotation(annotation):
        yield _create_annotation_dependant(annotation, path=path)
        return

    # a dependency made at runtime is analysed again on every resolve, and FastAPI only
    # ever sees its calls behind proxies released here - caching either would keep
    # whatever it carries alive past the request
    proxies: list[CallProxy] = []
    dependant = get_dependant(
        path=path or "",
        call=CallProxy(_value_factory(annotation), proxies),
    )

    try:
        yield dependant
    finally:
        release(proxies)


def _named_param(annotation: Any, /) -> Any:
    # resolved on its own, a marker has no parameter name - FastAPI would read `__value__`
    tp, *markers = get_args(annotation)

    for param in markers:
        match param:
            case params.Param():
                named = True
            case params.Form():
                # a form field is read by name, unless it is a model of the whole form
                named = not (inspect.isclass(tp) and issubclass(tp, BaseModel))
            case params.Body():
                named = bool(param.embed)
            case _:
                continue

        if named and not (param.alias or param.validation_alias):
            raise UnnamedParamError(param)

    return annotation


def _value_factory(annotation: Any, /) -> Callable[..., Coro[Any]]:
    async def _factory(__value__: Any) -> Any:
        return __value__

    cast(HasSignature, _factory).__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter(
                "__value__",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=annotation,
            ),
        ],
        return_annotation=Any,
    )

    return _factory


@lru_cache(maxsize=1024)
def _create_annotation_dependant(annotation: Any, /, *, path: str | None = None) -> Dependant:
    return get_dependant(
        path=path or "",
        call=_value_factory(annotation),
    )


def clear_dependant_cache() -> None:
    _create_annotation_dependant.cache_clear()


async def solve_arguments(
    dependant: Dependant,
    ctx: InjectionContext,
) -> dict[str, Any]:
    proxies: list[CallProxy] = []

    try:
        async with ctx.lock:
            body, embed_body_fields = await request_body(ctx.bound_request, dependant)

            solved = await solve_dependencies(
                request=ctx.bound_request,
                dependant=dependant,
                dependency_cache=cast("DependencyCache", ctx.cache_for(dependant)),
                dependency_overrides_provider=DetachedOverrides(ctx.dependency_overrides, proxies),
                # this parameter is deprecated and not used
                async_exit_stack=cast(AsyncExitStack, None),
                body=body,
                embed_body_fields=embed_body_fields,
            )
    except InvalidBodyError as exc:
        raise DependencyResolutionError(exc.errors) from None
    finally:
        release(proxies)

    if solved.errors:
        raise DependencyResolutionError(solved.errors)

    return solved.values


async def solve_value(
    dependant: Dependant,
    ctx: InjectionContext,
) -> Any:
    values = await solve_arguments(dependant, ctx)

    try:
        return values["__value__"]
    except KeyError:
        raise MissedDependencyError("__value__") from None


__all__ = [
    "DependencyResolutionError",
    "HasDependsHook",
    "MissedDependencyError",
    "UnnamedParamError",
    "clear_dependant_cache",
    "create_dependant",
    "open_dependant",
    "solve_arguments",
    "solve_value",
]
