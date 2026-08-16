from collections.abc import MutableMapping
from typing import Any

from fastapi import Request

from fastapi_injected import push_inject_scope
from fastapi_injected.scope import InjectScope, inside_inject_scope
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
        # a scope pushed by `push_inject_scope` is always bound, but the field is optional
        static_assert(is_equivalent_to(TypeOf[scope.request], Request | None))
        static_assert(is_equivalent_to(TypeOf[scope.bound_request], Request))
        static_assert(is_equivalent_to(TypeOf[scope.bound], bool))
        static_assert(is_equivalent_to(TypeOf[scope.path_format], str | None))
        static_assert(is_equivalent_to(TypeOf[scope.synthetic], bool))

    # an existing cache and request can be reused
    async with push_inject_scope(dependency_cache={}, request=None):
        pass

    async with inside_inject_scope(new_scope=True) as inner:
        static_assert(is_equivalent_to(TypeOf[inner], InjectScope))

    # overrides are part of the scope, both when it is pushed and afterwards
    async with push_inject_scope({Request: None}) as scope:
        static_assert(is_equivalent_to(TypeOf[scope.overrides], MutableMapping[Any, Any]))
        static_assert(is_equivalent_to(TypeOf[scope.dependency_overrides], MutableMapping[Any, Any]))
        static_assert(is_equivalent_to(TypeOf[scope.parent], InjectScope | None))

        with scope.override({Request: None}) as nested:
            static_assert(is_equivalent_to(TypeOf[nested], InjectScope))


def _current_scope() -> None:
    # outside of any scope there is none, so the result is optional
    static_assert(is_equivalent_to(TypeOf[InjectScope.current()], InjectScope | None))


async def _negatives() -> None:
    async with push_inject_scope(dependency_cache=[]):  # type: ignore[ty:invalid-argument-type]
        pass

    _ = InjectScope.current().dependency_cache  # type: ignore[ty:unresolved-attribute]
