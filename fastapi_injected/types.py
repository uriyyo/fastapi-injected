import inspect
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator, Mapping
from typing import TYPE_CHECKING, Annotated, Any, Protocol, TypeVar, runtime_checkable

from fastapi.types import DependencyCacheKey
from typing_extensions import TypeForm, sentinel

from ._params import Depends

if TYPE_CHECKING:
    Injected: Any = object()
else:
    Injected = sentinel("Injected")

if TYPE_CHECKING:
    type Dep[T] = Annotated[T, Depends()]
else:
    _T = TypeVar("_T")

    Dep = Annotated[_T, Depends()]

if TYPE_CHECKING:
    ArgMarker: Any = object()
else:
    ArgMarker = sentinel("ArgMarker")

if TYPE_CHECKING:
    type Arg[T] = Annotated[T, ...]
else:
    Arg = Annotated[_T, ArgMarker]

if TYPE_CHECKING:
    from typing import Annotated as DepFactory
else:

    class DepFactory:
        def __class_getitem__(cls, item: Any) -> Any:
            match item:
                case (tp, factory):
                    return Annotated[tp, Depends(factory)]
                case _:
                    raise TypeError(f"Invalid item: {item}")


type Coro[R] = Coroutine[Any, Any, R]

type AsyncFunc[**P, R] = Callable[P, Coro[R]]
type Func[**P, R] = Callable[P, R]

type Decorator[**P, R] = Callable[
    [Callable[P, R]],
    Callable[P, R],
]

type AsyncDecorator[**P, R] = Callable[
    [AsyncFunc[P, R]],
    AsyncFunc[P, R],
]

type DependencyCache = dict[DependencyCacheKey, Any]


class HasSignature(Protocol):
    __signature__: inspect.Signature


@runtime_checkable
class HasDependencyOverrides(Protocol):
    dependency_overrides: Mapping[Any, Any]


if TYPE_CHECKING:
    type DepOf[R] = TypeForm[R]
else:
    DepOf = Dep

type DepShape[R] = Coro[R] | AsyncIterator[R] | Iterator[R]
type DepReturn[R] = DepShape[R] | R
type DepDecl[**P, R] = Callable[P, DepShape[R]]

__all__ = [
    "Arg",
    "ArgMarker",
    "AsyncDecorator",
    "AsyncFunc",
    "Coro",
    "Decorator",
    "Dep",
    "DepDecl",
    "DepFactory",
    "DepOf",
    "DepReturn",
    "DepShape",
    "DependencyCache",
    "Func",
    "HasDependencyOverrides",
    "HasSignature",
    "Injected",
]
