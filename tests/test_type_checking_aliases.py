import sys
from typing import TYPE_CHECKING

import pytest

from fastapi_injected import DepFactory, Injected, inject, resolve

if TYPE_CHECKING:
    from decimal import Decimal

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(sys.version_info < (3, 14), reason="needs annotationlib forward references"),
]


async def provider() -> int:
    return 1


# `Decimal` is undefined at runtime
type TypeCheckingDep = DepFactory[Decimal, provider]
type NestedTypeCheckingDep = TypeCheckingDep


async def test_inject_resolves_an_alias_naming_a_type_checking_only_type() -> None:
    @inject
    async def handler(*, value: TypeCheckingDep = Injected) -> object:
        return value

    assert await handler() == 1


async def test_inject_resolves_a_nested_alias_naming_a_type_checking_only_type() -> None:
    @inject
    async def handler(*, value: NestedTypeCheckingDep = Injected) -> object:
        return value

    assert await handler() == 1


async def test_resolve_takes_an_alias_naming_a_type_checking_only_type() -> None:
    assert await resolve(TypeCheckingDep) == 1
