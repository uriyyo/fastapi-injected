import inspect
from collections.abc import Callable, Mapping
from functools import wraps
from typing import Annotated, Any, Self, cast

from fastapi import params
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_typed_annotation, get_typed_signature
from typing_inspection.typing_objects import is_typealiastype

from ._deps_tp import DependsSource, as_depends, is_arg, is_dep, is_request_param, unwrap_tp
from ._errors import InjectedError
from .types import Func, HasSignature, Injected

_DEP_ARG_PREFIX = "__dep_arg_"


class NotADependencyError(InjectedError, TypeError):
    def __init__(self, name: str, /) -> None:
        super().__init__(
            f"parameter {name!r} defaults to Injected but is not a dependency - "
            f"annotate it with Dep[...], Depends(...) or a request parameter like Header(...)",
        )

        self.name = name


def dep_arg_name(index: int, /) -> str:
    return f"{_DEP_ARG_PREFIX}{index}"


def dep_arg_index(name: str, /) -> int | None:
    if not name.startswith(_DEP_ARG_PREFIX):
        return None

    index = name[len(_DEP_ARG_PREFIX) :]

    return int(index) if index.isdigit() else None


def _typed_signature(
    func: Callable[..., Any],
    /,
    *,
    globalns: Mapping[str, Any] | None,
    localns: Mapping[str, Any] | None,
    include_return: bool,
) -> inspect.Signature:
    ns = {
        **getattr(inspect.unwrap(func), "__globals__", {}),
        **(globalns or {}),
        **(localns or {}),
    }

    sign = inspect.signature(func)

    returns = inspect.Signature.empty

    if include_return and sign.return_annotation is not inspect.Signature.empty:
        returns = get_typed_annotation(sign.return_annotation, ns)

    return inspect.Signature(
        [param.replace(annotation=get_typed_annotation(param.annotation, ns)) for param in sign.parameters.values()],
        return_annotation=returns,
    )


def _resolved_param(param: inspect.Parameter, /) -> inspect.Parameter | None:
    # what FastAPI resolves for an injectable function, None for what the caller passes
    if is_arg(param.annotation):
        resolved = False
    elif is_dep(param.annotation) or isinstance(param.default, params.Depends):
        resolved = True
    elif is_request_param(param.annotation):
        # a request parameter is the caller's, unless the function asks for it to be injected
        resolved = param.default is Injected
    else:
        resolved = False

    if not resolved:
        # nothing else would explain that default, and the missing `Dep[...]` would surface much later
        if param.default is Injected:
            raise NotADependencyError(param.name)

        return None

    if param.default is Injected:
        param = param.replace(default=inspect.Parameter.empty)

    if is_typealiastype(param.annotation):
        # FastAPI would evaluate the alias eagerly
        param = param.replace(annotation=unwrap_tp(param.annotation))

    return param


class Signature(inspect.Signature):
    __slots__ = ()

    @classmethod
    def of(
        cls,
        source: Callable[..., Any] | inspect.Signature,
        /,
        *,
        globalns: Mapping[str, Any] | None = None,
        localns: Mapping[str, Any] | None = None,
        include_return: bool = False,
    ) -> Self:
        match source:
            case inspect.Signature():
                sign = source
            case _ if globalns is None and localns is None and not include_return:
                sign = get_typed_signature(source)
            case _:
                sign = _typed_signature(source, globalns=globalns, localns=localns, include_return=include_return)

        return cls(
            [*sign.parameters.values()],
            return_annotation=sign.return_annotation,
        )

    @classmethod
    def build(cls, returns: Any = inspect.Signature.empty, /, **annotations: Any) -> Self:
        return cls(
            [
                inspect.Parameter(
                    name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=annotation,
                )
                for name, annotation in annotations.items()
            ],
            return_annotation=returns,
        )

    def __getitem__(self, key: int | str, /) -> inspect.Parameter:
        match key:
            case int():
                return [*self.parameters.values()][key]
            case str():
                return self.parameters[key]

    def deps_only(self) -> Self:
        return self.replace(
            parameters=[kept for param in self.parameters.values() if (kept := _resolved_param(param)) is not None],
        )

    def without_deps(self, dependant: Dependant, /) -> Self:
        resolved = {
            param.name
            for param in (
                *dependant.dependencies,
                *dependant.path_params,
                *dependant.query_params,
                *dependant.header_params,
                *dependant.cookie_params,
                *dependant.body_params,
            )
        }

        return self.replace(
            parameters=[param for param in self.parameters.values() if param.name not in resolved],
        )

    def with_dep_args(self, *annotations: Any) -> Self:
        present = [*self.parameters.values()]

        if len(annotations) > len(present):
            raise TypeError(f"{len(annotations)} dependencies cannot be bound to {len(present)} parameters")

        # placeholders FastAPI resolves by name, handed back by position at call time
        bound = [
            inspect.Parameter(
                dep_arg_name(index),
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=annotation,
            )
            for index, annotation in enumerate(annotations)
        ]

        return self.replace(parameters=[*bound, *present[len(annotations) :]])

    def provide(self, name: str, dep: DependsSource, /) -> Self:
        if name not in self.parameters:
            raise LookupError(f"no parameter named {name!r} in {self}")

        return self.replace(
            parameters=[
                inspect.Parameter(
                    name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=Annotated[Any, as_depends(dep)],
                )
                if param.name == name
                else param
                for param in self.parameters.values()
            ],
        )

    def apply[**P, R](self, func: Func[P, R], /) -> Func[P, R]:
        cast(HasSignature, func).__signature__ = self
        return func

    def wrap[**P, R](self, func: Func[P, R], /) -> Func[P, R]:
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def _async_call(*args: Any, **kwargs: Any) -> Any:
                return await func(*args, **kwargs)

            return self.apply(_async_call)  # type: ignore[ty:invalid-explicit-return]

        # generators too: FastAPI unwraps `__wrapped__` to tell what kind of call it is
        @wraps(func)
        def _call(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return self.apply(_call)


__all__ = [
    "NotADependencyError",
    "Signature",
]
