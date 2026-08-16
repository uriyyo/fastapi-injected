from collections.abc import AsyncGenerator

from fastapi import Depends, FastAPI, Request

from fastapi_injected import Dep, add_injected_scope, init_inject_scope

from .deps import (
    Child,
    Container,
    TypeOf,
    is_equivalent_to,
    static_assert,
)

app = FastAPI(dependencies=[Depends(init_inject_scope)])

static_assert(is_equivalent_to(TypeOf[add_injected_scope(app)], None))


def _init_scope_is_a_generator_dependency(request: Request) -> None:
    static_assert(is_equivalent_to(TypeOf[init_inject_scope(request)], AsyncGenerator[None]))


@app.get("/")
async def route(container: Dep[Container]) -> str:
    # inside a route the marker behaves exactly as it does outside of one
    static_assert(is_equivalent_to(TypeOf[container], Container))
    static_assert(is_equivalent_to(TypeOf[container.child], Child))

    return "ok"


def _negatives() -> None:
    add_injected_scope()  # type: ignore[ty:missing-argument]
    add_injected_scope(app=app)  # type: ignore[ty:positional-only-parameter-as-kwarg]
    add_injected_scope(object())  # type: ignore[ty:invalid-argument-type]
    init_inject_scope(object())  # type: ignore[ty:invalid-argument-type]
