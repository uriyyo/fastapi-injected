import inspect
from collections.abc import AsyncGenerator, Generator
from typing import TYPE_CHECKING, Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fastapi_injected.signature import Signature

if TYPE_CHECKING:
    from decimal import Decimal


def test_of_drops_the_return_annotation_by_default() -> None:
    def func(value: int) -> str:
        return str(value)  # pragma: no cover

    sign = Signature.of(func)

    assert sign.parameters["value"].annotation is int
    assert sign.return_annotation is inspect.Signature.empty


def test_of_keeps_the_return_annotation_when_asked() -> None:
    def func(value: int) -> str:
        return str(value)  # pragma: no cover

    def nothing() -> None:
        pass  # pragma: no cover

    assert Signature.of(func, include_return=True).return_annotation is str
    assert Signature.of(nothing, include_return=True).return_annotation is None


def test_of_reads_names_from_the_namespaces_given() -> None:
    class Local:
        pass

    def func(local: "Local", amount: "Decimal") -> "Local":
        return local  # pragma: no cover

    from decimal import Decimal  # noqa: PLC0415

    sign = Signature.of(func, localns={"Local": Local}, globalns={"Decimal": Decimal}, include_return=True)

    assert sign.parameters["local"].annotation is Local
    assert sign.parameters["amount"].annotation is Decimal
    assert sign.return_annotation is Local


def test_wrap_keeps_a_coroutine_a_coroutine() -> None:
    async def func() -> int:
        return 1  # pragma: no cover

    def sync() -> int:
        return 1  # pragma: no cover

    assert inspect.iscoroutinefunction(Signature.of(func).wrap(func))
    assert not inspect.iscoroutinefunction(Signature.of(sync).wrap(sync))


@pytest.mark.parametrize("kind", ["sync", "async"])
def test_a_wrapped_generator_dependency_keeps_its_teardown(kind: str) -> None:
    events: list[str] = []

    def sync_resource() -> Generator[str]:
        events.append("open")
        try:
            yield "resource"
        except ValueError:
            events.append("saw the error")
            raise
        finally:
            events.append("close")

    async def async_resource() -> AsyncGenerator[str]:
        events.append("open")
        try:
            yield "resource"
        except ValueError:
            events.append("saw the error")
            raise
        finally:
            events.append("close")

    resource = sync_resource if kind == "sync" else async_resource
    wrapped = Signature.of(resource).wrap(resource)

    app = FastAPI()

    @app.get("/ok")
    def ok(value: Annotated[str, Depends(wrapped)]) -> str:
        return value

    @app.get("/fail")
    def fail(value: Annotated[str, Depends(wrapped)]) -> str:
        raise ValueError(value)

    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/ok").json() == "resource"
    assert events == ["open", "close"]

    events.clear()
    assert client.get("/fail").status_code == 500
    assert events == ["open", "saw the error", "close"]
