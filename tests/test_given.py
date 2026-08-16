from dataclasses import dataclass

import pytest

from fastapi_injected import Given, is_dep, push_inject_scope, push_overrides, resolve

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class Token:
    value: str = "real"


async def test_given_resolves_to_the_value():
    assert await resolve(Given(42)) == 42


async def test_given_holds_anything():
    token = Token()

    assert await resolve(Given(token)) is token
    assert await resolve(Given([1, 2])) == [1, 2]
    assert await resolve(Given(None)) is None


async def test_given_is_a_dependency_marker():
    assert is_dep(Given(42))


ANNOTATED_TOKEN = Token("annotated")
AnnotatedToken = Given(ANNOTATED_TOKEN)


@dataclass
class Holder:
    token: AnnotatedToken


async def test_given_can_be_used_as_an_annotation():
    assert (await resolve(Holder)).token is ANNOTATED_TOKEN


async def test_constants_holding_equal_values_are_one_dependency():
    first, second = Token("same"), Token("same")

    async with push_inject_scope():
        assert await resolve(Given(first)) is first
        # the second constant is the same dependency, so what the first one built is reused
        assert await resolve(Given(second)) is first


async def test_constants_holding_unhashable_values_are_their_own():
    first, second = ["same"], ["same"]

    async with push_inject_scope():
        assert await resolve(Given(first)) is first
        # nothing says two equal lists are the same value, so they are told apart by identity
        assert await resolve(Given(second)) is second


async def test_given_can_be_overridden():
    given = Given(Token())

    with push_overrides({given: Token("fake")}):
        assert (await resolve(given)).value == "fake"
