from fastapi import params

from ._dataclass import MakeDataclass


class Depends(MakeDataclass, params.Depends, frozen=True):
    pass


class Security(Depends, params.Security, frozen=True):
    def __post_init__(self) -> None:
        if self.scopes is not None:
            object.__setattr__(self, "scopes", tuple(self.scopes))


__all__ = [
    "Depends",
    "Security",
]
