from fastapi_injected._cache import ScopeCache


def dep() -> int:
    return 1


def other_dep() -> int:
    return 2


DEP_KEY = (dep, (), "")
OTHER_KEY = (other_dep, (), "")


def test_scope_cache_reads_through_to_fallbacks():
    cache = ScopeCache({}, [({DEP_KEY: 1}, frozenset())])

    assert cache[DEP_KEY] == 1
    assert DEP_KEY in cache


def test_scope_cache_hides_overridden_entries():
    cache = ScopeCache({}, [({DEP_KEY: 1, OTHER_KEY: 2}, frozenset({dep}))])

    assert DEP_KEY not in cache
    assert cache[OTHER_KEY] == 2


def test_scope_cache_keeps_its_own_entries():
    fallback = {DEP_KEY: 1}
    cache = ScopeCache({}, [(fallback, frozenset({dep}))])

    cache[DEP_KEY] = 3

    # the override built its own value, and the scope it was pushed into keeps its one
    assert cache[DEP_KEY] == 3
    assert fallback[DEP_KEY] == 1


def test_scope_cache_iterates_over_visible_entries():
    cache = ScopeCache(
        {DEP_KEY: 3},
        [
            ({DEP_KEY: 1, OTHER_KEY: 2}, frozenset({dep})),
            ({OTHER_KEY: 4}, frozenset()),
        ],
    )

    assert dict(cache) == {DEP_KEY: 3, OTHER_KEY: 2}
    assert len(cache) == 2


def test_scope_cache_deletes_from_its_own_entries():
    cache = ScopeCache({DEP_KEY: 3})

    del cache[DEP_KEY]

    assert DEP_KEY not in cache


def test_scope_cache_misses():
    cache = ScopeCache({}, [({}, frozenset())])

    assert cache.get(DEP_KEY) is None
    assert not cache
