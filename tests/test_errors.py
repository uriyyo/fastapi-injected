from typing import Annotated

import pytest
from fastapi import Depends, Header
from fastapi.exceptions import RequestValidationError

from fastapi_injected import (
    DependencyResolutionError,
    DepFactory,
    Injected,
    InjectedError,
    NoInjectionContextError,
    NotADependencyError,
    UnboundContextError,
    UnnamedParamError,
    UnsetContextValueError,
    inject,
    resolve,
)
from fastapi_injected.ext import InvalidMarkerError, MissedDependencyError, NotAsyncError, UnboundDepArgsError
from fastapi_injected.fastapi import ConnectionNotAvailableError, MissingDependencyCacheError
from fastapi_injected.reflect import RouteNotFoundError

pytestmark = pytest.mark.asyncio


async def _needs_header(x_trace: Annotated[str, Header()]) -> str:
    return x_trace


type Trace = Annotated[str, Depends(_needs_header)]


async def test_resolve_reports_what_could_not_be_resolved():
    with pytest.raises(DependencyResolutionError) as exc_info:
        await resolve(Trace)

    [error] = exc_info.value.errors

    assert error["type"] == "missing"
    assert error["loc"] == ("header", "x-trace")


async def test_inject_reports_what_could_not_be_resolved():
    @inject
    async def func(*, trace: Trace = Injected) -> str:
        return trace  # pragma: no cover

    with pytest.raises(DependencyResolutionError):
        await func()


async def test_resolution_error_is_a_value_error():
    # it used to be a plain `ValueError`, and code catching that still works
    with pytest.raises(ValueError, match="missing"):
        await resolve(Trace)


async def test_resolution_error_becomes_a_validation_error():
    with pytest.raises(DependencyResolutionError) as exc_info:
        await resolve(Trace)

    validation_error = exc_info.value.as_validation_error()

    assert isinstance(validation_error, RequestValidationError)
    assert validation_error.errors() == exc_info.value.errors


async def test_resolution_error_keeps_the_errors_in_its_args():
    with pytest.raises(DependencyResolutionError) as exc_info:
        await resolve(Trace)

    assert exc_info.value.args == (exc_info.value.errors,)


async def test_every_error_is_an_injected_error():
    errors = [
        DependencyResolutionError,
        UnnamedParamError,
        NotADependencyError,
        UnboundContextError,
        NoInjectionContextError,
        UnsetContextValueError,
        MissedDependencyError,
        NotAsyncError,
        UnboundDepArgsError,
        InvalidMarkerError,
        MissingDependencyCacheError,
        ConnectionNotAvailableError,
        RouteNotFoundError,
    ]

    assert all(issubclass(error, InjectedError) for error in errors)


async def test_a_wrong_dep_factory_shows_the_expected_form():
    with pytest.raises(InvalidMarkerError, match=r"DepFactory\[Settings, get_settings\]"):
        DepFactory[int]
