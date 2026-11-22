from collections.abc import Callable
from functools import cache
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, status

from ._bind import _dep_annotation
from ._calls import is_static_annotation
from ._deps_tp import unwrap_tp
from .signature import Signature


def not_found() -> Exception:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _build(annotation: Any, error: Callable[[], BaseException], /) -> Callable[..., Any]:
    async def require(value: Any) -> Any:
        if value is None:
            raise error()

        return value

    return Signature.build(value=annotation).apply(require)


# one callable per source dependency, so FastAPI shares its result within a request
_build_static = cache(_build)


def not_none(tp: Any, dep: Any, error: Callable[[], BaseException] = not_found, /) -> Any:
    annotation = unwrap_tp(_dep_annotation(dep))
    build = _build_static if is_static_annotation(annotation) else _build

    return Annotated[tp, Depends(build(annotation, error))]


if TYPE_CHECKING:
    from typing import Annotated as NotNone
else:

    class NotNone:
        """`NotNone[T, dep]`: what `dep` resolves to, or `error()` raised when it is `None` (404 by default)."""

        def __class_getitem__(cls, item: Any) -> Any:
            match item:
                case (tp, dep, *error) if len(error) <= 1:
                    return not_none(tp, dep, *error)
                case _:
                    raise TypeError(f"NotNone[...] takes a type, a dependency and optionally an error, got {item!r}")


__all__ = [
    "NotNone",
    "not_found",
    "not_none",
]
