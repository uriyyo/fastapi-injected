from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient

from fastapi_injected import Dep, Injected, init_inject_scope, inject, resolve

from .deps import Container

app = FastAPI(
    dependencies=[
        Depends(init_inject_scope),
    ],
)

client = TestClient(app)


@inject
async def _func(
    *,
    container: Dep[Container] = Injected,
) -> Container:
    return container


@app.get("/")
async def route(container: Dep[Container]) -> str:
    assert await resolve(Container) is container
    assert await _func() is container

    return ""


def test_cache_is_working() -> None:
    result = client.get("/")
    assert result.status_code == status.HTTP_200_OK
