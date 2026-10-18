import inspect
from collections.abc import Callable, Generator
from enum import StrEnum, auto
from functools import wraps
from typing import Annotated, Any, NotRequired, Self, TypedDict, Unpack, cast

from fastapi import params
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_typed_signature

from ._deps_tp import DependsSource, as_depends, is_arg, is_dep, is_request_param
from .types import Func, HasSignature, Injected


class NotADependencyError(TypeError):
    def __init__(self, name: str, /) -> None:
        super().__init__(
            f"parameter {name!r} defaults to Injected but is not a dependency - "
            f"annotate it with Dep[...], Depends(...) or a request parameter like Header(...)",
        )

        self.name = name


type SignatureSource = Callable[..., Any] | inspect.Signature


class ParamRole(StrEnum):
    dep = auto()  # Dep[...] or a Depends(...) default
    request = auto()  # Header(), Query(), Body(), ... annotation
    arg = auto()  # Arg[...]
    plain = auto()


class _ParamChanges(TypedDict):
    name: NotRequired[str]
    kind: NotRequired[inspect._ParameterKind]
    annotation: NotRequired[Any]
    default: NotRequired[Any]


class Signature(inspect.Signature):
    __slots__ = ()

    @classmethod
    def of(cls, source: SignatureSource, /) -> Self:
        match source:
            case inspect.Signature():
                sign = source
            case _:
                sign = get_typed_signature(source)

        return cls(
            [*sign.parameters.values()],
            return_annotation=sign.return_annotation,
        )

    @staticmethod
    def role(param: inspect.Parameter, /) -> ParamRole:
        match param:
            case _ if is_arg(param.annotation):
                return ParamRole.arg
            case _ if is_dep(param.annotation) or isinstance(param.default, params.Depends):
                return ParamRole.dep
            case _ if is_request_param(param.annotation):
                return ParamRole.request
            case _:
                return ParamRole.plain

    def select(self, *roles: ParamRole) -> Generator[inspect.Parameter]:
        for param in self.parameters.values():
            if self.role(param) in roles:
                yield param

    @property
    def annotations(self) -> dict[str, Any]:
        return {
            param.name: param.annotation
            for param in self.parameters.values()
            if param.annotation is not inspect.Parameter.empty
        }

    @property
    def defaults(self) -> dict[str, Any]:
        return {
            param.name: param.default
            for param in self.parameters.values()
            if param.default is not inspect.Parameter.empty
        }

    def add(self, *extra: inspect.Parameter) -> Self:
        added = [
            param.replace(
                kind=inspect.Parameter.KEYWORD_ONLY,
            )
            for param in extra
            if param.name not in self.parameters
        ]

        present = [*self.parameters.values()]

        var_kw = [param for param in present if param.kind is inspect.Parameter.VAR_KEYWORD]
        rest = [param for param in present if param.kind is not inspect.Parameter.VAR_KEYWORD]

        return self.replace(parameters=[*rest, *added, *var_kw])

    def drop(self, *names: str) -> Self:
        return self.replace(parameters=[param for param in self.parameters.values() if param.name not in names])

    def update(self, name: str, /, **changes: Unpack[_ParamChanges]) -> Self:
        if name not in self.parameters:
            raise LookupError(f"no parameter named {name!r} in {self}")

        return self.replace(
            parameters=[
                param.replace(**changes) if param.name == name else param for param in self.parameters.values()
            ],
        )

    def prepend(self, *extra: inspect.Parameter) -> Self:
        added = [
            param.replace(kind=inspect.Parameter.POSITIONAL_OR_KEYWORD)
            for param in extra
            if param.name not in self.parameters
        ]

        return self.replace(parameters=[*added, *self.parameters.values()])

    def rename(self, old: str, new: str, /) -> Self:
        return self.update(old, name=new)

    def returns(self, annotation: Any, /) -> Self:
        return self.replace(return_annotation=annotation)

    def add_dep(
        self,
        name: str,
        dep: DependsSource,
        /,
        *,
        annotation: Any = Any,
    ) -> Self:
        param = inspect.Parameter(
            name,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=Annotated[annotation, as_depends(dep)],
        )

        return self.add(param)

    def prepare(self) -> Self:
        def _is_dep(param: inspect.Parameter) -> bool:
            match self.role(param):
                case ParamRole.dep:
                    return True
                case ParamRole.request:
                    # a request parameter is the caller's, unless the function asks for it to be injected
                    return param.default is Injected
                case _:
                    return False

        def _keep(param: inspect.Parameter) -> inspect.Parameter | None:
            if not _is_dep(param):
                # nothing else would explain that default, and the missing `Dep[...]` would
                # otherwise surface much later as a missing argument
                if param.default is Injected:
                    raise NotADependencyError(param.name)

                return None

            if param.default is Injected:
                param = param.replace(default=inspect.Parameter.empty)

            return param

        return self.replace(
            parameters=[kept for param in self.parameters.values() if (kept := _keep(param)) is not None],
        )

    def strip(self, dependant: Dependant, /) -> Self:
        params_ = (
            *dependant.dependencies,
            *dependant.path_params,
            *dependant.query_params,
            *dependant.header_params,
            *dependant.cookie_params,
            *dependant.body_params,
        )

        return self.drop(
            *(name for param in params_ if (name := param.name)),
        )

    def apply[**P, R](self, func: Func[P, R], /) -> Func[P, R]:
        cast(HasSignature, func).__signature__ = self
        return func

    def wrap(self, func: Callable[..., Any], /) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def _async_call(*args: Any, **kwargs: Any) -> Any:
                return await func(*args, **kwargs)

            return self.apply(_async_call)

        @wraps(func)
        def _call(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return self.apply(_call)


__all__ = [
    "NotADependencyError",
    "ParamRole",
    "Signature",
    "SignatureSource",
]
