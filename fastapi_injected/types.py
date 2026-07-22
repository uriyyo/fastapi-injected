import inspect
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Annotated, Any, Protocol, TypeVar

from fastapi import Depends
from fastapi.types import DependencyCacheKey
from typing_extensions import sentinel

if TYPE_CHECKING:
    Inejected: Any = object()
else:
    Inejected = sentinel("Injected")

if TYPE_CHECKING:
    type Dep[T] = Annotated[T, Depends()]
else:
    _T = TypeVar("_T")

    Dep = Annotated[_T, Depends()]


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

type DependencyCache = dict[DependencyCacheKey, Any]


class HasSignature(Protocol):
    __signature__: inspect.Signature


__all__ = [
    "AsyncFunc",
    "Coro",
    "Decorator",
    "Dep",
    "DepFactory",
    "DependencyCache",
    "Func",
    "HasSignature",
    "Inejected",
]
