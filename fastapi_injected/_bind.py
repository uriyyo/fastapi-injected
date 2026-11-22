import inspect
from collections.abc import Callable, Sequence
from functools import wraps
from typing import Any, Concatenate, overload

from fastapi.params import Depends

from ._deps_tp import annotated_parts, as_annotation, unwrap_tp
from ._errors import InjectedError
from .deps import _named_param
from .signature import Signature, dep_arg_index, dep_arg_name
from .types import AsyncFunc, DepOf, Func


class UnboundDepArgsError(InjectedError, ValueError):
    def __init__(self, indexes: Sequence[int], /) -> None:
        super().__init__(f"bound dependencies are not the leading ones: {sorted(indexes)}")

        self.indexes = indexes


def _dep_annotation(dep: DepOf[Any] | Callable[..., Any], /) -> Any:
    match dep:
        case _ if annotated_parts(dep) is not None:
            # bound, a marker is read under the made-up `__dep_arg_N` name, so it must name its own
            _named_param(unwrap_tp(dep))
            return dep
        case _ if isinstance(dep, Depends) or callable(dep):
            return as_annotation(dep)
        case _:
            return dep


def signature_with_deps(
    func: Func[..., Any],
    /,
    *deps: DepOf[Any] | Callable[..., Any],
) -> Signature:
    return Signature.of(func).with_dep_args(*(_dep_annotation(dep) for dep in deps))


def take_dep_args(kwargs: dict[str, Any], /) -> list[Any]:
    indexes = sorted(index for name in kwargs if (index := dep_arg_index(name)) is not None)

    # they are passed by name and taken back by position, so a gap in them would move
    # every argument after it - it is a bug in whoever built the signature, not an input
    if indexes != [*range(len(indexes))]:
        raise UnboundDepArgsError(indexes)

    return [kwargs.pop(dep_arg_name(index)) for index in indexes]


class NotAsyncError(InjectedError, TypeError):
    def __init__(self, func: Callable[..., Any], /) -> None:
        super().__init__(f"{func!r} must be an async function")

        self.func = func


def is_async_callable(func: Any, /) -> bool:
    """Whether calling `func` gives a coroutine - through `functools.partial`, `functools.wraps` and `__call__`."""

    return inspect.iscoroutinefunction(inspect.unwrap(func)) or (
        not inspect.isclass(func) and inspect.iscoroutinefunction(getattr(func, "__call__", None))  # noqa: B004
    )


def remap_dep_args[**P, R](func: AsyncFunc[P, R], /) -> AsyncFunc[P, R]:
    if not is_async_callable(func):
        raise NotAsyncError(func)

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> R:
        return await func(*args, *take_dep_args(kwargs), **kwargs)

    return wrapper


# a dependency bound to a parameter, however it was written - what it resolves to is
# decided by the parameter, so `Callable` says nothing about the type here
type _BoundDep[T] = DepOf[T] | Callable[..., Any]


@overload
def bind_deps[**P, R](func: AsyncFunc[P, R], /) -> AsyncFunc[P, R]: ...


@overload
def bind_deps[T1, **P, R](
    func: AsyncFunc[Concatenate[T1, P], R],
    dep1: _BoundDep[T1],
    /,
) -> AsyncFunc[P, R]: ...


@overload
def bind_deps[T1, T2, **P, R](
    func: AsyncFunc[Concatenate[T1, T2, P], R],
    dep1: _BoundDep[T1],
    dep2: _BoundDep[T2],
    /,
) -> AsyncFunc[P, R]: ...


@overload
def bind_deps[T1, T2, T3, **P, R](
    func: AsyncFunc[Concatenate[T1, T2, T3, P], R],
    dep1: _BoundDep[T1],
    dep2: _BoundDep[T2],
    dep3: _BoundDep[T3],
    /,
) -> AsyncFunc[P, R]: ...


@overload
def bind_deps[T1, T2, T3, T4, **P, R](
    func: AsyncFunc[Concatenate[T1, T2, T3, T4, P], R],
    dep1: _BoundDep[T1],
    dep2: _BoundDep[T2],
    dep3: _BoundDep[T3],
    dep4: _BoundDep[T4],
    /,
) -> AsyncFunc[P, R]: ...


@overload
def bind_deps[T1, T2, T3, T4, T5, **P, R](
    func: AsyncFunc[Concatenate[T1, T2, T3, T4, T5, P], R],
    dep1: _BoundDep[T1],
    dep2: _BoundDep[T2],
    dep3: _BoundDep[T3],
    dep4: _BoundDep[T4],
    dep5: _BoundDep[T5],
    /,
) -> AsyncFunc[P, R]: ...


# what is bound beyond that, or bound from a sequence, leaves the parameters open
@overload
def bind_deps[R](
    func: AsyncFunc[..., R],
    /,
    *deps: _BoundDep[Any],
) -> AsyncFunc[..., R]: ...


def bind_deps[**P, R](
    func: AsyncFunc[P, R],
    /,
    *deps: DepOf[Any] | Callable[..., Any],
) -> AsyncFunc[..., R]:
    return signature_with_deps(func, *deps).apply(remap_dep_args(func))


__all__ = [
    "NotAsyncError",
    "UnboundDepArgsError",
    "bind_deps",
    "dep_arg_name",
    "is_async_callable",
    "remap_dep_args",
    "signature_with_deps",
    "take_dep_args",
]
