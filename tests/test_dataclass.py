from dataclasses import field, fields

import pytest

from fastapi_injected import MakeDataclass, resolve


class Point(MakeDataclass):
    x: int
    y: int = 0


class FrozenPoint(MakeDataclass, frozen=True, kw_only=True):
    x: int


class Untouched(MakeDataclass, eq=False):
    x: int


class Holder(MakeDataclass):
    values: list[int] = field(default_factory=list)


def test_subclass_is_a_dataclass():
    point = Point(1)

    assert [f.name for f in fields(point)] == ["x", "y"]
    assert point == Point(1, 0)
    assert repr(point) == "Point(x=1, y=0)"


def test_dataclass_options_are_passed_through():
    assert FrozenPoint(x=1) == FrozenPoint(x=1)

    with pytest.raises(TypeError):
        FrozenPoint(1)  # type: ignore[ty:too-many-positional-arguments]


def test_equal_instances_hash_equally():
    assert hash(Point(1)) == hash(Point(1))
    assert {Point(1): "value"}[Point(1, 0)] == "value"


def test_unhashable_fields_fall_back_to_identity():
    holder = Holder([1, 2])

    assert hash(holder) == object.__hash__(holder)
    assert {holder: "value"}[holder] == "value"


def test_without_eq_it_hashes_by_identity():
    one, other = Untouched(1), Untouched(1)

    assert one != other
    assert hash(one) != hash(other)


class Dependency(MakeDataclass):
    values: list[int] = field(default_factory=list)

    def __call__(self) -> list[int]:
        return self.values


@pytest.mark.asyncio
async def test_unhashable_dependency_can_be_resolved():
    # dependants are cached by the callable, which has to be hashable to get there
    dependency = Dependency([1, 2])

    assert await resolve(dependency) == [1, 2]
