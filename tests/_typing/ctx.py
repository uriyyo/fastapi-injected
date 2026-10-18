from collections.abc import MutableMapping
from typing import Any

from fastapi import Request, WebSocket

from fastapi_injected import injection_ctx
from fastapi_injected.ctx import InjectionContext, ensure_injection_ctx
from fastapi_injected.types import BoundConnection, DependencyCache

from .deps import (
    TypeOf,
    is_equivalent_to,
    static_assert,
)


async def _ctx() -> None:
    async with injection_ctx() as ctx:
        static_assert(is_equivalent_to(TypeOf[ctx], InjectionContext))
        static_assert(is_equivalent_to(TypeOf[ctx.dependency_cache], DependencyCache))
        # a context pushed by `injection_ctx` is always bound, but the field is optional
        static_assert(is_equivalent_to(TypeOf[ctx.request], BoundConnection | None))
        static_assert(is_equivalent_to(TypeOf[ctx.bound_request], BoundConnection))
        static_assert(is_equivalent_to(TypeOf[ctx.bound_request], Request | WebSocket))
        static_assert(is_equivalent_to(TypeOf[ctx.bound], bool))
        static_assert(is_equivalent_to(TypeOf[ctx.path_format], str | None))
        static_assert(is_equivalent_to(TypeOf[ctx.synthetic], bool))

    # an existing cache and request can be reused
    async with injection_ctx(dependency_cache={}, request=None):
        pass

    async with ensure_injection_ctx(new_ctx=True) as inner:
        static_assert(is_equivalent_to(TypeOf[inner], InjectionContext))

    # overrides are part of the context, both when it is pushed and afterwards
    async with injection_ctx({Request: None}) as ctx:
        static_assert(is_equivalent_to(TypeOf[ctx.own_overrides], MutableMapping[Any, Any]))
        static_assert(is_equivalent_to(TypeOf[ctx.dependency_overrides], MutableMapping[Any, Any]))
        static_assert(is_equivalent_to(TypeOf[ctx.parent], InjectionContext | None))

        with ctx.override({Request: None}) as nested:
            static_assert(is_equivalent_to(TypeOf[nested], InjectionContext))


async def _bound_to(request: Request, websocket: WebSocket) -> None:
    # a context is bound to whichever the route has - a request or a websocket
    async with injection_ctx(request=request):
        pass

    async with injection_ctx(request=websocket):
        pass


def _current_ctx() -> None:
    # outside of any context there is none, so the result is optional
    static_assert(is_equivalent_to(TypeOf[InjectionContext.current()], InjectionContext | None))


async def _negatives() -> None:
    async with injection_ctx(dependency_cache=[]):  # type: ignore[ty:invalid-argument-type]
        pass

    _ = InjectionContext.current().dependency_cache  # type: ignore[ty:unresolved-attribute]

    async with injection_ctx(request=object()):  # type: ignore[ty:invalid-argument-type]
        pass
