import dataclasses
import inspect
import typing
from collections.abc import Callable
from typing import Any, get_args, get_origin

from fastapi.dependencies.utils import get_typed_signature
from fastapi.params import Depends

from ._deps_tp import unwrap_tp


def annotated(tp: Any, /, *metadata: Any) -> Any:
    # `Annotated[...]` goes through typing's own cache, which holds on to the last
    # aliases it built - and with them whatever value a runtime marker carries
    return typing._AnnotatedAlias(tp, metadata)  # type: ignore[ty:unresolved-attribute] # noqa: SLF001


def is_static_call(call: Any, /) -> bool:
    # what source code wrote down lives as long as the process anyway, so caching
    # by it keeps nothing extra alive - an instance or a closure may carry request data
    if inspect.isclass(call):
        return True

    # a builtin bound to an instance, like `cache.get`, carries that instance along
    if inspect.isbuiltin(call):
        return call.__self__ is None or inspect.ismodule(call.__self__)

    # `__qualname__` is what `functools.wraps` copied over, the code knows where it was defined
    if inspect.isfunction(call):
        return "<locals>" not in call.__code__.co_qualname

    return False


def _depends_metadata(annotation: Any, /) -> tuple[Any, list[Any]] | None:
    annotation = unwrap_tp(annotation)

    if get_origin(annotation) is not typing.Annotated:
        return None

    tp, *metadata = get_args(annotation)

    return tp, metadata


def is_static_annotation(annotation: Any, /) -> bool:
    match _depends_metadata(annotation):
        case (tp, metadata):
            return all(
                is_static_call(tp if meta.dependency is None else meta.dependency)
                for meta in metadata
                if isinstance(meta, Depends)
            )
        case _:
            return False


class CallProxy:
    # what FastAPI is handed in place of a call made at runtime: its classification
    # caches keep every call they are shown, and once released this is all they keep
    __slots__ = ("_hash", "_proxies", "_signature", "call")

    def __init__(self, call: Callable[..., Any], proxies: list["CallProxy"], /) -> None:
        self.call: Callable[..., Any] | None = call
        self._proxies = proxies
        self._signature: inspect.Signature | None = None

        try:
            self._hash = hash(call)
        except TypeError:
            self._hash = id(call)

        proxies.append(self)

    @property
    def __wrapped__(self) -> Callable[..., Any]:
        # FastAPI unwraps a call to tell a coroutine from a generator, so it sees the
        # real one - a released proxy has nothing left to show
        if self.call is None:
            raise AttributeError("__wrapped__")

        return self.call

    @property
    def __signature__(self) -> inspect.Signature:
        # FastAPI builds the dependencies of this call from its signature, so whatever
        # was made at runtime among them is handed over behind a proxy as well
        if self._signature is None:
            sign = get_typed_signature(self.__wrapped__)
            self._signature = sign.replace(
                parameters=[self._detach_param(param) for param in sign.parameters.values()],
            )

        return self._signature

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.__wrapped__(*args, **kwargs)

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        # equal to the call it stands for, so it finds the same cache entries and overrides
        if self.call is None:
            return other is self

        return self.call == unwrap_proxy(other)

    def release(self) -> None:
        self.call = None
        self._signature = None
        self._proxies = []

    def _detach_depends(self, depends: Depends, /) -> Depends:
        if depends.dependency is None or is_static_call(depends.dependency):
            return depends

        return dataclasses.replace(depends, dependency=CallProxy(depends.dependency, self._proxies))

    def _detach_param(self, param: inspect.Parameter, /) -> inspect.Parameter:
        if isinstance(param.default, Depends):
            param = param.replace(default=self._detach_depends(param.default))

        match _depends_metadata(param.annotation):
            case (tp, metadata):
                detached = [self._detach_depends(meta) if isinstance(meta, Depends) else meta for meta in metadata]

                if any(new is not old for new, old in zip(detached, metadata, strict=True)):
                    param = param.replace(annotation=annotated(tp, *detached))

        return param


def unwrap_proxy(call: Any, /) -> Any:
    if isinstance(call, CallProxy) and call.call is not None:
        return call.call

    return call


__all__ = [
    "CallProxy",
    "annotated",
    "is_static_annotation",
    "is_static_call",
    "unwrap_proxy",
]
