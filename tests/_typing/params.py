from typing import Annotated

from fastapi import params

from fastapi_injected import Depends, Security

from .deps import (
    ContextState,
    ctx_dep,
    is_assignable_to,
    is_subtype_of,
    static_assert,
)

# they are the fastapi params they wrap, so anything taking one takes these
static_assert(is_subtype_of(Depends, params.Depends))
static_assert(is_subtype_of(Security, params.Security))
static_assert(is_subtype_of(Security, Depends))
static_assert(is_assignable_to(Annotated[ContextState, Security(ctx_dep, scopes=["me"])], ContextState))


def _params() -> None:
    Depends()
    Depends(ctx_dep, use_cache=False)
    Security(ctx_dep, scopes=["me"], use_cache=False)


def _negatives() -> None:
    Depends(use_cache="yes")  # type: ignore[ty:invalid-argument-type]
    Security(ctx_dep, scopes=1)  # type: ignore[ty:invalid-argument-type]
