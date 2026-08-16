from dataclasses import dataclass
from typing import Annotated, Any

import pytest
from fastapi import Depends

from fastapi_injected import Given, bind_deps, inject, push_inject_scope, push_overrides, resolve, signature_with_deps
from fastapi_injected._bind import UnboundDepArgsError, dep_arg_name, remap_dep_args, take_dep_args

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


async def describe(doc: Doc, role: Role, *, loud: bool = False) -> str:
    return f"{doc.title}:{role.name}{'!' if loud else ''}"


async def test_bound_dependencies_are_resolved():
    bound = bind_deps(describe, Given(Doc()), RoleDep)

    assert await resolve(bound) == "readme:admin"


async def test_bound_function_can_be_injected():
    bound = inject(bind_deps(describe, Given(Doc()), RoleDep))

    assert await bound() == "readme:admin"


async def test_parameters_that_are_not_bound_are_left_alone():
    async def has_default(doc: Doc, greeting: str = "hi") -> str:
        return f"{greeting} {doc.title}"

    assert await resolve(bind_deps(has_default, Given(Doc()))) == "hi readme"


async def test_bound_dependencies_can_be_overridden():
    bound = bind_deps(describe, Given(Doc()), RoleDep)

    with push_overrides({role_dep: Role("guest")}):
        assert await resolve(bound) == "readme:guest"


async def test_bound_dependencies_share_the_scope_cache():
    async def which(role: Role) -> Role:
        return role

    bound = bind_deps(which, RoleDep)

    async with push_inject_scope():
        assert await resolve(bound) is await resolve(bound)


async def test_binding_more_than_there_are_parameters():
    with pytest.raises(TypeError, match="cannot be bound"):
        bind_deps(describe, RoleDep, RoleDep, RoleDep, RoleDep)


@pytest.mark.parametrize(
    "dep",
    [
        role_dep,
        Role,
        Depends(role_dep),
        Annotated[Role, Depends(role_dep)],
        RoleDep,
    ],
)
async def test_a_dependency_can_be_bound_however_it_is_written(dep):
    # a callable is a dependency the same way `resolve` takes one, not a parameter of its own
    assert await resolve(bind_deps(describe, Given(Doc()), dep)) == "readme:admin"


async def test_signature_with_deps_names_the_bound_parameters() -> None:
    sign = signature_with_deps(describe, Given(Doc()), RoleDep)

    assert [*sign.parameters] == [dep_arg_name(0), dep_arg_name(1), "loud"]


async def test_bound_arguments_have_to_be_the_leading_ones() -> None:
    # a gap would shift every argument after it, which is what makes it worth checking
    kwargs: dict[str, Any] = {dep_arg_name(0): 1, dep_arg_name(2): 3}

    with pytest.raises(UnboundDepArgsError) as exc_info:
        take_dep_args(kwargs)

    assert exc_info.value.indexes == [0, 2]


async def test_remap_dep_args_passes_them_positionally():
    async def method(self: str, first: int, second: int) -> str:
        return f"{self}:{first}:{second}"

    remapped = remap_dep_args(method)

    assert await remapped("self", **{dep_arg_name(0): 1, dep_arg_name(1): 2}) == "self:1:2"


async def test_more_dependencies_than_the_overloads_cover():
    async def six(one: int, two: int, three: int, four: int, five: int, six: int) -> int:  # noqa: PLR0913, PLR0917
        return one + two + three + four + five + six

    bound = bind_deps(six, *(Given(number) for number in range(1, 7)))

    assert await resolve(bound) == 21
