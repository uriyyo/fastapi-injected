from fastapi import Request

from fastapi_injected import push_inject_scope
from fastapi_injected.scope import InjectScope, current_inject_scope, inside_inject_scope
from fastapi_injected.types import DependencyCache

from .deps import (
    TypeOf,
    is_equivalent_to,
    static_assert,
)


async def _scope() -> None:
    async with push_inject_scope() as scope:
        static_assert(is_equivalent_to(TypeOf[scope], InjectScope))
        static_assert(is_equivalent_to(TypeOf[scope.dependency_cache], DependencyCache))
        static_assert(is_equivalent_to(TypeOf[scope.request], Request))
        static_assert(is_equivalent_to(TypeOf[scope.path_format], str | None))
        static_assert(is_equivalent_to(TypeOf[scope.synthetic], bool))

    # an existing cache and request can be reused
    async with push_inject_scope(dependency_cache={}, request=None):
        pass

    async with inside_inject_scope(new_scope=True) as inner:
        static_assert(is_equivalent_to(TypeOf[inner], InjectScope))


def _current_scope() -> None:
    # outside of any scope there is none, so the result is optional
    static_assert(is_equivalent_to(TypeOf[current_inject_scope()], InjectScope | None))


async def _negatives() -> None:
    async with push_inject_scope({}):  # type: ignore[ty:too-many-positional-arguments]
        pass

    async with push_inject_scope(dependency_cache=[]):  # type: ignore[ty:invalid-argument-type]
        pass

    _ = current_inject_scope().dependency_cache  # type: ignore[ty:unresolved-attribute]
