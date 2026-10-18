from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request, WebSocket

from fastapi_injected import Dep, add_injection, bind_injection_ctx

from .deps import (
    Child,
    Container,
    TypeOf,
    is_equivalent_to,
    static_assert,
)

app = FastAPI()

add_injection(app)

static_assert(is_equivalent_to(TypeOf[add_injection(app)], None))


def _init_ctx_is_a_generator_dependency(request: Request, websocket: WebSocket) -> None:
    static_assert(is_equivalent_to(TypeOf[bind_injection_ctx(request)], AsyncGenerator[None]))
    static_assert(is_equivalent_to(TypeOf[bind_injection_ctx(websocket)], AsyncGenerator[None]))


@app.get("/")
async def route(container: Dep[Container]) -> str:
    # inside a route the marker behaves exactly as it does outside of one
    static_assert(is_equivalent_to(TypeOf[container], Container))
    static_assert(is_equivalent_to(TypeOf[container.child], Child))

    return "ok"


def _negatives() -> None:
    add_injection()  # type: ignore[ty:missing-argument]
    add_injection(app=app)  # type: ignore[ty:positional-only-parameter-as-kwarg]
    add_injection(object())  # type: ignore[ty:invalid-argument-type]
    bind_injection_ctx(object())  # type: ignore[ty:invalid-argument-type]
