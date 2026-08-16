import inspect
from typing import cast

from fastapi import params
from fastapi.dependencies.models import Dependant

from ._deps_tp import is_arg, is_dep
from .types import Decorator, Func, HasSignature, Injected


class NotADependencyError(TypeError):
    def __init__(self, name: str, /) -> None:
        super().__init__(
            f"parameter {name!r} defaults to Injected but is not a dependency - "
            f"annotate it with Dep[...] or Depends(...)",
        )

        self.name = name


def update_func_sign[**P, R](func: Func[P, R], sign: inspect.Signature) -> Func[P, R]:
    cast("HasSignature", func).__signature__ = sign
    return func


def _is_dep_param(param: inspect.Parameter) -> bool:
    if is_arg(param.annotation):
        return False

    return is_dep(param.annotation) or isinstance(param.default, params.Depends)


def prepare_sign(sign: inspect.Signature) -> inspect.Signature:
    def _keep(param: inspect.Parameter) -> inspect.Parameter | None:
        if not _is_dep_param(param):
            # nothing else would explain that default, and the missing `Dep[...]` would
            # otherwise surface much later as a missing argument
            if param.default is Injected:
                raise NotADependencyError(param.name)

            return None

        if param.default is Injected:
            param = param.replace(default=inspect.Parameter.empty)

        return param

    return sign.replace(
        parameters=[kept for param in sign.parameters.values() if (kept := _keep(param)) is not None],
    )


def strip_deps_from_sign(
    sign: inspect.Signature,
    dependent: Dependant,
) -> inspect.Signature:
    names = {param.name for param in dependent.dependencies}

    return sign.replace(parameters=[param for param in sign.parameters.values() if param.name not in names])


def strip_sign[**P, R](dependant: Dependant, /) -> Decorator[P, R]:
    def decorator(func: Func[P, R]) -> Func[P, R]:
        return update_func_sign(
            func,
            strip_deps_from_sign(inspect.signature(func), dependant),
        )

    return decorator


__all__ = [
    "NotADependencyError",
    "prepare_sign",
    "strip_deps_from_sign",
    "strip_sign",
    "update_func_sign",
]
