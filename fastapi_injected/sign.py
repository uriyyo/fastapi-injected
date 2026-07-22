import inspect
from typing import cast

from fastapi.dependencies.models import Dependant

from .types import Decorator, Func, HasSignature, Inejected


def update_func_sign[**P, R](func: Func[P, R], sign: inspect.Signature) -> Func[P, R]:
    cast("HasSignature", func).__signature__ = sign
    return func


def prepare_sign(sign: inspect.Signature) -> inspect.Signature:
    def _update_param(param: inspect.Parameter) -> inspect.Parameter:
        if param.default is Inejected:
            param = param.replace(default=inspect.Parameter.empty)

        return param

    return sign.replace(parameters=[_update_param(param) for param in sign.parameters.values()])


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
    "prepare_sign",
    "strip_deps_from_sign",
    "strip_sign",
    "update_func_sign",
]
