from typing import Any

from fastapi.exceptions import RequestValidationError

from fastapi_injected import DependencyResolutionError, NotADependencyError

from .deps import (
    TypeOf,
    is_equivalent_to,
    is_subtype_of,
    static_assert,
)

# catching it as what resolution used to raise keeps working
static_assert(is_subtype_of(DependencyResolutionError, ValueError))

# a parameter that cannot be injected is a mistake in how it was written, not a runtime failure
static_assert(is_subtype_of(NotADependencyError, TypeError))


def _errors(error: DependencyResolutionError) -> None:
    static_assert(is_equivalent_to(TypeOf[error.errors], list[Any]))
    static_assert(is_equivalent_to(TypeOf[error.as_validation_error()], RequestValidationError))


def _negatives() -> None:
    DependencyResolutionError()  # type: ignore[ty:missing-argument]
    DependencyResolutionError(errors=[])  # type: ignore[ty:positional-only-parameter-as-kwarg]
