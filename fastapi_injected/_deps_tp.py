import sys
import types
import typing
from collections.abc import Callable
from typing import Annotated, Any, TypeVar, get_args, get_origin

from fastapi import params
from fastapi.params import Body, Depends, Param
from typing_inspection.typing_objects import is_typealiastype

from ._errors import InvalidMarkerError
from .types import ArgMarker, HasDependsHook


def _alias_value(alias: Any, /) -> Any:
    try:
        return alias.__value__
    except NameError:
        # a `TYPE_CHECKING`-only name: leave it a forward reference
        if sys.version_info < (3, 14):
            raise

        from annotationlib import Format, call_evaluate_function  # noqa: PLC0415

        return call_evaluate_function(alias.evaluate_value, Format.FORWARDREF)


def unwrap_tp(tp: Any) -> Any:
    # PEP 695 aliases can be nested, e.g. `type A = B` where `type B = Annotated[...]`
    while is_typealiastype(tp):
        tp = _alias_value(tp)

    return tp


def annotated_parts(tp: Any, /) -> tuple[Any, tuple[Any, ...]] | None:
    # `Annotated[X, *metadata]` as `(X, metadata)`, through type aliases; None for anything else
    tp = unwrap_tp(tp)

    if get_origin(tp) is not Annotated:
        return None

    base, *metadata = get_args(tp)

    return base, (*metadata,)


def _metadata(tp: Any, /) -> tuple[Any, ...]:
    match annotated_parts(tp):
        case (_, metadata):
            return metadata
        case _:
            return ()


def is_dep(tp: Any) -> bool:
    return any(isinstance(meta, Depends) for meta in _metadata(tp))


def is_request_param(tp: Any) -> bool:
    # a marker FastAPI reads from the request: `Header()`, `Query()`, `Path()`, `Cookie()`, the body ones
    return any(isinstance(meta, Param | Body) for meta in _metadata(tp))


def is_arg(tp: Any) -> bool:
    return any(meta is ArgMarker for meta in _metadata(tp))


def _enforce_dep(tp: Any) -> Any:
    tp = unwrap_tp(tp)

    if not is_dep(tp):
        msg = f"expected a `Dep[...]` or `DepFactory[...]` annotation, got {tp!r}"
        raise InvalidMarkerError(msg)

    return tp


def unwrap_dep_tp(obj: Any, /) -> Any:
    obj = _enforce_dep(obj)

    match get_args(obj)[0]:
        case TypeVar():  # bare `Dep`, used without a type argument
            return Any
        case tp:
            return tp


def unwrap_dep_dependency(obj: Any, /) -> Any:
    obj = _enforce_dep(obj)
    tp, *metadatas = get_args(obj)
    for metadata in metadatas:
        if isinstance(metadata, Depends) and metadata.dependency is not None:
            return metadata.dependency

    return tp


def strip_annotation(tp: Any, /) -> Any:
    # Annotated[X, ...] -> X, X | None -> X, repeated until nothing changes
    while True:
        match get_origin(tp):
            case typing.Annotated:
                tp = get_args(tp)[0]
            case typing.Union | types.UnionType:
                args = [arg for arg in get_args(tp) if arg is not type(None)]
                if len(args) != 1:
                    return tp
                tp = args[0]
            case _:
                return tp


type DependsSource = params.Depends | HasDependsHook[..., Any] | Callable[..., Any]


def as_depends(dep: DependsSource, /) -> params.Depends:
    match dep:
        case params.Depends():
            return dep
        case HasDependsHook():
            return dep.__get_depends__()
        case _:
            return params.Depends(dep)


def as_annotation(dep: DependsSource | params.Param | params.Body, /) -> Any:
    match dep:
        case params.Param() | params.Body():
            marker = dep
        case _:
            marker = as_depends(dep)

    # built directly: typing's cache would keep the last aliases, and the markers they carry, alive
    return typing._AnnotatedAlias(Any, (marker,))  # type: ignore[ty:missing-attribute] # noqa: SLF001


__all__ = [
    "DependsSource",
    "annotated_parts",
    "as_annotation",
    "as_depends",
    "is_arg",
    "is_dep",
    "is_request_param",
    "strip_annotation",
    "unwrap_dep_dependency",
    "unwrap_dep_tp",
    "unwrap_tp",
]
