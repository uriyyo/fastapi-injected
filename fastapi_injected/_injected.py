from collections.abc import Iterator
from typing import Any

from fastapi.dependencies.utils import get_typed_signature

from ._bind import remap_dep_args, signature_with_deps
from ._dataclass import MakeDataclass
from ._deps_tp import is_dep
from .types import DepOf


class MakeInjected(MakeDataclass):
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # only the call this class brought itself - an inherited one was wrapped already
        if "__call__" in cls.__dict__:
            cls.__call__ = remap_dep_args(cls.__call__)  # type: ignore[ty:invalid-assignment]

    def __post_init__(self) -> None:
        super().__post_init__()
        self.__signature__ = signature_with_deps(self.__call__, *self.__deps__())

    def __deps__(self) -> Iterator[DepOf[Any]]:
        for param in get_typed_signature(type(self)).parameters.values():
            if is_dep(param.annotation):
                yield getattr(self, param.name)


__all__ = [
    "MakeInjected",
]
