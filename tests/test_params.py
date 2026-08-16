from typing import Annotated

import pytest
from fastapi import params
from fastapi.security import SecurityScopes

from fastapi_injected import Depends, Security, is_dep, push_inject_scope, resolve


async def scopes_dep(scopes: SecurityScopes) -> list[str]:
    return scopes.scopes


class Unhashable:
    __hash__ = None  # type: ignore[ty:invalid-assignment]

    async def __call__(self) -> str:
        return "value"


def test_they_are_fastapi_params():
    assert isinstance(Depends(scopes_dep), params.Depends)
    assert isinstance(Security(scopes_dep), params.Security)
    assert isinstance(Security(scopes_dep), params.Depends)


def test_scopes_are_written_as_documented():
    security = Security(scopes_dep, scopes=["items:read"])

    assert security.scopes == ("items:read",)
    assert is_dep(Annotated[list[str], security])


def test_equal_params_hash_equally():
    assert hash(Depends(scopes_dep)) == hash(Depends(scopes_dep))
    assert Security(scopes_dep, scopes=["me"]) == Security(scopes_dep, scopes=["me"])
    assert hash(Security(scopes_dep, scopes=["me"])) == hash(Security(scopes_dep, scopes=("me",)))


def test_a_scoped_annotation_can_be_hashed():
    # the annotation is the key a dependant is cached by, and a list of scopes used to break it
    assert hash(Annotated[list[str], Security(scopes_dep, scopes=["items:read", "me"])])

    with pytest.raises(TypeError, match="unhashable type: 'list'"):
        hash(Annotated[list[str], params.Security(scopes_dep, scopes=["items:read", "me"])])


def test_unhashable_dependencies_fall_back_to_identity():
    depends = Depends(Unhashable())

    assert hash(depends) == object.__hash__(depends)
    assert hash(Annotated[str, depends])


@pytest.mark.asyncio
async def test_a_scoped_dependency_resolves():
    scoped = Annotated[list[str], Security(scopes_dep, scopes=["items:read", "me"])]

    assert await resolve(scoped) == ["items:read", "me"]


@pytest.mark.asyncio
async def test_equal_params_are_one_dependency():
    calls = 0

    async def counted() -> int:
        nonlocal calls
        calls += 1
        return calls

    async with push_inject_scope():
        assert await resolve(Annotated[int, Security(counted, scopes=["me"])]) == 1
        # the same scopes written as another list are the same dependency, so it is cached
        assert await resolve(Annotated[int, Security(counted, scopes=["me"])]) == 1
        # different scopes are not
        assert await resolve(Annotated[int, Security(counted, scopes=["other"])]) == 2

    assert calls == 2
