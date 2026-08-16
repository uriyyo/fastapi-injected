import inspect
from collections.abc import Callable, Sequence
from functools import wraps
from typing import Annotated, Any, Concatenate, get_origin, overload

from fastapi.dependencies.utils import get_typed_signature
from fastapi.params import Depends

from ._deps_tp import unwrap_tp
from .sign import update_func_sign
from .types import AsyncFunc, DepOf, Func

_DEP_ARG_PREFIX = "__dep_arg_"


class UnboundDepArgsError(ValueError):
    def __init__(self, indexes: Sequence[int], /) -> None:
        super().__init__(f"bound dependencies are not the leading ones: {sorted(indexes)}")

        self.indexes = indexes


def dep_arg_name(index: int, /) -> str:
    return f"{_DEP_ARG_PREFIX}{index}"


def _dep_arg_index(name: str, /) -> int | None:
    if not name.startswith(_DEP_ARG_PREFIX):
        return None

    index = name[len(_DEP_ARG_PREFIX) :]

    return int(index) if index.isdigit() else None


def _is_annotation(tp: Any, /) -> bool:
    return get_origin(unwrap_tp(tp)) is Annotated


def _dep_annotation(dep: DepOf[Any] | Callable[..., Any], /) -> Any:
    if isinstance(dep, Depends):
        return Annotated[Any, dep]

    if _is_annotation(dep) or not callable(dep):
        return dep

    return Annotated[Any, Depends(dep)]


def signature_with_deps(
    func: Func[..., Any],
    /,
    *deps: DepOf[Any] | Callable[..., Any],
) -> inspect.Signature:
    sign = get_typed_signature(func)
    parameters = [*sign.parameters.values()]

    if len(deps) > len(parameters):
        msg = f"{len(deps)} dependencies cannot be bound to {len(parameters)} parameters"
        raise TypeError(msg)

    return sign.replace(
        parameters=[
            *[
                inspect.Parameter(
                    dep_arg_name(index),
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=_dep_annotation(dep),
                )
                for index, dep in enumerate(deps)
            ],
            *parameters[len(deps) :],
        ],
    )


def take_dep_args(kwargs: dict[str, Any], /) -> list[Any]:
    indexes = sorted(index for name in kwargs if (index := _dep_arg_index(name)) is not None)

    # they are passed by name and taken back by position, so a gap in them would move
    # every argument after it - it is a bug in whoever built the signature, not an input
    if indexes != [*range(len(indexes))]:
        raise UnboundDepArgsError(indexes)

    return [kwargs.pop(dep_arg_name(index)) for index in indexes]


def remap_dep_args[**P, R](func: AsyncFunc[P, R], /) -> AsyncFunc[P, R]:
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
    return update_func_sign(
        remap_dep_args(func),
        signature_with_deps(func, *deps),
    )


__all__ = [
    "UnboundDepArgsError",
    "bind_deps",
    "dep_arg_name",
    "remap_dep_args",
    "signature_with_deps",
    "take_dep_args",
]
