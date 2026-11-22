import inspect
from collections.abc import AsyncGenerator, Generator
from typing import TYPE_CHECKING, Annotated, Any

import pytest
from fastapi import Depends, FastAPI, Header
from fastapi.dependencies.utils import get_dependant
from fastapi.testclient import TestClient

from fastapi_injected import Arg, Dep, Injected, NotADependencyError
from fastapi_injected.signature import Signature, dep_arg_name

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


class Svc:
    pass


def test_build_makes_positional_or_keyword_params_and_takes_returns_first() -> None:
    sign = Signature.build(int, value=str, returns=bytes)

    assert [(p.name, p.kind, p.annotation) for p in sign.parameters.values()] == [
        ("value", inspect.Parameter.POSITIONAL_OR_KEYWORD, str),
        ("returns", inspect.Parameter.POSITIONAL_OR_KEYWORD, bytes),
    ]
    assert sign.return_annotation is int
    assert Signature.build().return_annotation is inspect.Signature.empty


def test_deps_only_keeps_what_fastapi_resolves() -> None:
    def func(  # noqa: PLR0913
        plain: int,
        arg: Arg[str],
        dep: Dep[int],
        marked: Any = Depends(int),  # noqa: B008
        *,
        header: Annotated[str, Header()] = "x",
        injected: Annotated[str, Header()] = Injected,
        service: Dep[int] = Injected,
    ) -> None:
        pass  # pragma: no cover

    sign = Signature.of(func).deps_only()

    assert [*sign.parameters] == ["dep", "marked", "injected", "service"]
    assert sign.parameters["injected"].default is inspect.Parameter.empty
    assert sign.parameters["service"].default is inspect.Parameter.empty


def test_deps_only_rejects_injected_on_a_plain_param() -> None:
    def func(value: int = Injected) -> None:
        pass  # pragma: no cover

    with pytest.raises(NotADependencyError, match="'value'"):
        Signature.of(func).deps_only()


def test_without_deps_leaves_what_the_caller_passes() -> None:
    def func(value: int, dep: Dep[Svc] = Injected, *, header: Annotated[str, Header()] = Injected) -> None:
        pass  # pragma: no cover

    sign = Signature.of(func)
    dependant = get_dependant(path="", call=sign.deps_only().wrap(func))

    assert [*sign.without_deps(dependant).parameters] == ["value"]


def test_with_dep_args_replaces_the_leading_params() -> None:
    def func(a: int, /, b: str, *, c: bytes) -> None:
        pass  # pragma: no cover

    sign = Signature.of(func).with_dep_args(Dep[int])

    assert [(p.name, p.kind) for p in sign.parameters.values()] == [
        (dep_arg_name(0), inspect.Parameter.POSITIONAL_OR_KEYWORD),
        ("b", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        ("c", inspect.Parameter.KEYWORD_ONLY),
    ]
    assert sign.parameters[dep_arg_name(0)].annotation == Dep[int]

    with pytest.raises(TypeError, match="cannot be bound"):
        Signature.of(func).with_dep_args(int, int, int, int)


def test_provide_resolves_a_param_from_a_dependency() -> None:
    def current() -> str:
        return "me"

    async def handler(*, user: str = "nobody") -> str:
        return user

    Signature.of(handler).provide("user", current).apply(handler)

    app = FastAPI()
    app.get("/")(handler)

    assert TestClient(app).get("/").json() == "me"

    with pytest.raises(LookupError):
        Signature.of(handler).provide("missing", current)


def test_getitem_takes_a_position_or_a_name() -> None:
    def func(a: int, b: str) -> None:
        pass  # pragma: no cover

    sign = Signature.of(func)

    assert sign[0] is sign["a"]
    assert sign[-1].name == "b"
    assert sign["b"].annotation is str

    with pytest.raises(IndexError):
        sign[2]

    with pytest.raises(KeyError):
        sign["c"]
