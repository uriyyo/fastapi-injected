import inspect
from collections import deque
from collections.abc import Callable, Collection, Generator, Iterable, Mapping
from contextlib import suppress
from enum import StrEnum, auto
from typing import Any, Literal, assert_never, cast

from fastapi import params
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant
from fastapi.security.base import SecurityBase

from fastapi_injected._cache import overridden_calls
from fastapi_injected._calls import unwrap_proxy
from fastapi_injected._deps_tp import as_depends
from fastapi_injected.signature import Signature
from fastapi_injected.types import HasDependsHook, Injected


class ParamKind(StrEnum):
    path = auto()
    query = auto()
    header = auto()
    cookie = auto()
    body = auto()


type DependantSource = Dependant | params.Depends | Callable[..., Any]


def _callable_dependant(func: Callable[..., Any], /, *, path: str) -> Dependant:
    # the view FastAPI would have of the callable, with `Injected` defaults dropped so
    # they read as dependencies; a wrapper keeps the original signature untouched
    sign = Signature.of(func)

    for param in sign.parameters.values():
        if param.default is Injected:
            sign = sign.update(
                param.name,
                default=inspect.Parameter.empty,
            )

    dependant = get_dependant(path=path, call=sign.wrap(func))
    dependant.call = func

    return dependant


def as_dependant(node: DependantSource, /, *, path: str | None = None) -> Dependant:
    match node:
        case Dependant():
            if path is not None and node.path != path:
                msg = f"dependant was built for path {node.path!r}, not {path!r}"
                raise ValueError(msg)

            return node
        case params.Depends() | HasDependsHook():
            if (dependency := as_depends(node).dependency) is None:
                # a bare Depends() only means something next to the annotation it sits on
                raise TypeError("Depends() without a dependency has no dependant of its own")

            return get_dependant(path=path or "", call=dependency)
        case _:
            return _callable_dependant(
                cast(Callable[..., Any], node),
                path=path or "",
            )


def _bfs(root: Dependant) -> Generator[Dependant]:
    queue = deque([root])
    while queue:
        node = queue.popleft()
        yield node
        queue.extend(node.dependencies)


def _dfs(root: Dependant) -> Generator[Dependant]:
    yield root

    for node in root.dependencies:
        yield from _dfs(node)


def iter_dependant(
    root: DependantSource,
    /,
    *,
    mode: Literal["bfs", "dfs"] = "bfs",
) -> Generator[Dependant]:
    root = as_dependant(root)

    match mode:
        case "bfs":
            yield from _bfs(root)
        case "dfs":
            yield from _dfs(root)
        case _:
            assert_never(mode)


def iter_calls(
    root: DependantSource,
    /,
    *,
    expand: Callable[[Any], Iterable[Any]] | None = None,
) -> Generator[Any]:
    seen: set[int] = set()

    def _expand(call: Any, /) -> Generator[Any]:
        if id(call) in seen:
            return

        seen.add(id(call))

        yield call

        if expand is None:
            return

        for sub_call in expand(call):
            yield from _expand(sub_call)

    it = iter_dependant(
        root,
        mode="dfs",
    )

    with suppress(StopIteration):
        next(it)  # skip root

    for node in it:
        if node.call is not None:
            yield from _expand(unwrap_proxy(node.call))


def iter_security(root: DependantSource, /) -> Generator[tuple[SecurityBase, list[str]]]:
    seen: set[tuple[int, tuple[str, ...]]] = set()

    for node in iter_dependant(root, mode="dfs"):
        scopes = [*(node.own_oauth_scopes or ())]

        if not isinstance(node.call, SecurityBase):
            continue

        key = (id(node.call), (*scopes,))

        if key not in seen:
            seen.add(key)
            yield node.call, scopes


def iter_params(root: DependantSource, /) -> Generator[tuple[Dependant, ParamKind, Any]]:
    for node in iter_dependant(root, mode="dfs"):
        for kind in ParamKind:
            for field in getattr(node, f"{kind}_params"):
                yield node, kind, field


def find_dependant(root: DependantSource, call: Any, /) -> list[Dependant]:

    def _search(node: Dependant, /) -> list[Dependant] | None:
        if unwrap_proxy(node.call) is call:
            return [node]

        for sub in node.dependencies:
            if (found := _search(sub)) is not None:
                return [node, *found]

        return None

    return _search(as_dependant(root)) or []


def iter_overridden(
    root: DependantSource,
    overrides: Collection[Any] | Mapping[Any, Any],
    /,
) -> frozenset[Any]:
    return overridden_calls(as_dependant(root), overrides)


__all__ = [
    "DependantSource",
    "ParamKind",
    "as_dependant",
    "find_dependant",
    "iter_calls",
    "iter_dependant",
    "iter_overridden",
    "iter_params",
    "iter_security",
]
