from typing import Annotated, Any, TypeVar, get_args, get_origin

from fastapi.params import Depends
from typing_inspection.typing_objects import is_typealiastype


def unwrap_tp(tp: Any) -> Any:
    # PEP 695 aliases can be nested, e.g. `type A = B` where `type B = Annotated[...]`
    while is_typealiastype(tp):
        tp = tp.__value__

    return tp


def _get_annotated_metadata(tp: Any) -> tuple[Any, ...]:
    if get_origin(tp) is Annotated:
        return get_args(tp)[1:]

    return ()


def is_dep(tp: Any) -> bool:
    tp = unwrap_tp(tp)

    return any(isinstance(tp, Depends) for tp in _get_annotated_metadata(tp))


def _enforce_dep(tp: Any) -> Any:
    tp = unwrap_tp(tp)

    if not is_dep(tp):
        msg = f"Expected a Dep, got {tp!r}"
        raise TypeError(msg)

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


__all__ = [
    "is_dep",
    "unwrap_dep_dependency",
    "unwrap_dep_tp",
    "unwrap_tp",
]
