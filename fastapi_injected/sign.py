import inspect
from typing import cast

from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import analyze_param

from .types import Decorator, Func, HasSignature, Inejected


def update_func_sign[**P, R](func: Func[P, R], sign: inspect.Signature) -> Func[P, R]:
    cast("HasSignature", func).__signature__ = sign
    return func


def prepare_sign(sign: inspect.Signature) -> inspect.Signature:
    def _update_param(param: inspect.Parameter) -> inspect.Parameter:
        if param.default is Inejected:
            param = param.replace(default=inspect.Parameter.empty)

        return param

    def _is_depends(param: inspect.Parameter) -> bool:
        result = analyze_param(
            param_name=param.name,
            annotation=param.annotation,
            value=param.default,
            is_path_param=False,
        )

        return result.depends is not None

    return sign.replace(
        parameters=[_update_param(param) for param in sign.parameters.values() if _is_depends(param)],
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
    "prepare_sign",
    "strip_deps_from_sign",
    "strip_sign",
    "update_func_sign",
]
