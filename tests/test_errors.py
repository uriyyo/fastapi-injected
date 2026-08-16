from typing import Annotated

import pytest
from fastapi import Depends, Header
from fastapi.exceptions import RequestValidationError

from fastapi_injected import DependencyResolutionError, Injected, inject, resolve

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
