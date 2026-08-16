import inspect
from dataclasses import dataclass
from typing import Annotated

import pytest
from fastapi import Depends

from fastapi_injected import Given, MakeInjected, push_inject_scope, push_overrides, resolve
from fastapi_injected.types import DepOf

pytestmark = pytest.mark.asyncio


@dataclass
class Role:
    name: str = "admin"


async def role_dep() -> Role:
    return Role()


type RoleDep = Annotated[Role, Depends(role_dep)]


@dataclass
class Doc:
    title: str = "readme"


class IsOwner(MakeInjected):
    doc: DepOf[Doc]
    role: DepOf[Role]
    loud: bool = False

    async def __call__(self, doc: Doc, role: Role) -> str:
        return f"{doc.title}:{role.name}{'!' if self.loud else ''}"


async def test_fields_become_the_dependencies_of_the_call():
    assert await resolve(IsOwner(doc=Given(Doc()), role=RoleDep)) == "readme:admin"


async def test_fields_that_are_not_markers_stay_plain():
    assert await resolve(IsOwner(doc=Given(Doc()), role=RoleDep, loud=True)) == "readme:admin!"


async def test_what_it_depends_on_can_be_overridden():
    check = IsOwner(doc=Given(Doc()), role=RoleDep)

    with push_overrides({role_dep: Role("guest")}):
        assert await resolve(check) == "readme:guest"


async def test_equal_instances_are_one_dependency():
    async with push_inject_scope():
        first = IsOwner(doc=Given(Doc("same")), role=RoleDep)
        second = IsOwner(doc=Given(Doc("same")), role=RoleDep)

        assert first == second
        assert await resolve(first) == await resolve(second)


async def test_the_class_still_reports_its_own_signature():
    # the signature is served per instance, so the constructor keeps answering for the class
    assert [*inspect.signature(IsOwner).parameters] == ["doc", "role", "loud"]


async def test_a_subclass_keeps_working():
    class IsLoudOwner(IsOwner):
        async def __call__(self, doc: Doc, role: Role) -> str:
            return (await super().__call__(doc, role)).upper()

    assert await resolve(IsLoudOwner(doc=Given(Doc()), role=RoleDep)) == "README:ADMIN"


async def test_a_subclass_that_only_adds_fields_keeps_the_call():
    class WithExtra(IsOwner):
        extra: str = "extra"

    assert await resolve(WithExtra(doc=Given(Doc()), role=RoleDep)) == "readme:admin"


async def test_a_subclass_can_add_its_own_post_init():
    class Counted(IsOwner):
        counted: bool = False

        def __post_init__(self) -> None:
            # the signature is built there, so a subclass has to chain to it
            super().__post_init__()
            self.counted = True

    check = Counted(doc=Given(Doc()), role=RoleDep)

    assert check.counted
    assert await resolve(check) == "readme:admin"
