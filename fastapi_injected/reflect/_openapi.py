from collections.abc import Generator, Mapping
from typing import Any

from fastapi import FastAPI

HTTP_METHODS = frozenset(
    {
        "get",
        "put",
        "post",
        "delete",
        "options",
        "head",
        "patch",
        "trace",
    },
)

type _SchemaSource = FastAPI | Mapping[str, Any]


def _schema(source: _SchemaSource, /) -> Mapping[str, Any]:
    match source:
        case FastAPI():
            return source.openapi()
        case _:
            return source


def iter_operations(source: _SchemaSource, /) -> Generator[tuple[str, str, dict[str, Any]]]:
    for path, item in _schema(source).get("paths", {}).items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield path, method.upper(), operation


def operation_for(source: _SchemaSource, method: str, path: str, /) -> dict[str, Any]:
    try:
        return _schema(source)["paths"][path][method.lower()]
    except KeyError:
        raise LookupError(f"no operation for {method.upper()} {path}") from None


__all__ = [
    "HTTP_METHODS",
    "iter_operations",
    "operation_for",
]
