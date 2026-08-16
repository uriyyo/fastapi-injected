# fastapi-injected

Yet another attempt to reuse FastAPI's dependency injection outside of request handlers.

This is an opinionated library: it takes the DI machinery you already know from FastAPI (`Depends`, generator dependencies with teardown, dependency caching) and makes it usable in plain async functions — background jobs, CLI commands, workers, scripts — without a `Request` in sight.

## Installation

```sh
pip install fastapi-injected
```

Requires Python 3.12+.

## Usage

Declare dependencies as regular classes and annotate fields with `Dep[...]`:

```python
from dataclasses import dataclass
from typing import AsyncIterator

from fastapi_injected import Dep, DepFactory, Injected, inject


@dataclass
class Session:
    closed: bool = False


async def session_dep() -> AsyncIterator[Session]:
    session = Session()
    try:
        yield session
    finally:
        session.closed = True


@dataclass
class Repository:
    session: DepFactory[Session, session_dep]


@dataclass
class Service:
    repo: Dep[Repository]


@inject
async def handler(*, service: Dep[Service] = Injected) -> None:
    ...  # service is built and injected, session is closed on exit


await handler()
```

- `Dep[T]` — resolve `T` by calling it, same as FastAPI's `Annotated[T, Depends()]`.
- `DepFactory[T, factory]` — resolve `T` via a factory, same as `Annotated[T, Depends(factory)]`. Generator factories get proper teardown.
- `Arg[T]` — mark a parameter as a plain caller-supplied argument, for types pydantic cannot validate. See [Non-pydantic arguments](#non-pydantic-arguments).
- `Injected` — a sentinel default that exists purely to make type checkers happy: without it they would complain about a missing argument at call sites. At runtime the parameter is always filled in by `@inject`.

Injected parameters mix freely with regular ones — pass your own arguments as usual and the rest is injected:

```python
@inject
async def add(a: int, b: int, *, service: Dep[Service] = Injected) -> int:
    ...


result = await add(1, 2)
```

### Non-pydantic arguments

Regular parameters still go through FastAPI's parameter analysis, so their annotations have to be valid pydantic field types. A plain class that pydantic cannot handle makes `@inject` fail at decoration time:

```python
class Connection:  # not a pydantic-friendly type
    ...


@inject
async def handler(conn: Connection, *, service: Dep[Service] = Injected) -> None:
    ...  # FastAPIError: Invalid args for response field!
```

Wrap such parameters in `Arg[...]` to hide them from that analysis:

```python
from fastapi_injected import Arg


@inject
async def handler(conn: Arg[Connection], *, service: Dep[Service] = Injected) -> None:
    ...


await handler(connection)
```

`Arg[T]` is a no-op for type checkers — the parameter stays typed as `T` — and at runtime it only tells `@inject` that this argument comes from the caller, not from the dependency graph. It is needed only for annotations pydantic rejects; ordinary types work without it.

### Resolving a type directly

No decorator needed — resolve a dependency graph on demand:

```python
from fastapi_injected import resolve

service = await resolve(Service)
```

Like `@inject`, `resolve` accepts `new_scope=True` to force a fresh scope instead of reusing the surrounding one.

### Scopes and caching

By default every call to an injected function gets its own scope: dependencies are built, cached within the call, and torn down when it returns. Wrap several calls in `push_inject_scope()` to share one cache (and defer teardown to the end of the scope):

```python
from fastapi_injected import push_inject_scope

async with push_inject_scope():
    a = await handler()  # dependencies built here
    b = await handler()  # same instances reused
# generator dependencies are torn down here
```

Use `@inject(new_scope=True)` to opt a function out of the surrounding scope and always get fresh dependencies.

### Overriding dependencies

`push_overrides` swaps dependencies out for the duration of a `with` block — handy in tests, or anywhere you need to run the same code against a different implementation:

```python
from fastapi_injected import push_overrides

with push_overrides({Session: Session(closed=True)}):
    await handler()  # gets the override instead of the real dependency
```

A key can be the dependency itself, or the annotation you wrote in the signature — `Dep[Session]` and `DepFactory[Session, session_dep]` both work and are normalized to the same underlying dependency:

```python
with push_overrides({DepFactory[Session, session_dep]: my_session}):
    ...
```

Values are used as-is, but two wrappers make the intent explicit and cover the ambiguous cases:

- `ValueOverride(value)` — always inject `value`, even when it is itself callable.
- `FactoryOverride(factory)` — call `factory` to produce the value. Sync, async, and generator factories are all supported, with the same teardown semantics as regular dependencies.

```python
from fastapi_injected import FactoryOverride, ValueOverride

with push_overrides(
    {
        Session: ValueOverride(fake_session),
        Repository: FactoryOverride(lambda: FakeRepository()),
    },
):
    ...
```

Overrides apply to the whole graph, not just top-level parameters — overriding a nested dependency changes what its dependents receive. Nested `push_overrides` blocks merge, with the innermost one winning.

Because the surrounding scope caches resolved dependencies, an override pushed after something has already been built would silently have no effect. To catch that, `push_overrides` raises `NonFreshScopeError` if the current scope already holds cached dependencies. Pass `require_fresh_scope=False` if you know what you are doing and want the override to apply only to what has not been resolved yet:

```python
async with push_inject_scope():
    await handler()  # dependencies cached here

    with push_overrides({Session: fake}):  # raises NonFreshScopeError
        ...
```

### Inspecting annotations

A few helpers are exported for code that needs to reason about `Dep[...]` annotations — building override maps, custom decorators, and the like:

- `is_dep(tp)` — whether `tp` is a `Dep`/`DepFactory` annotation.
- `unwrap_dep_tp(tp)` — the annotated type (`Any` for a bare `Dep`).
- `unwrap_dep_dependency(tp)` — the callable that resolves it: the factory for `DepFactory[T, factory]`, the type itself for `Dep[T]`.

### FastAPI request integration

Inside a FastAPI app, `@inject`-ed functions and `resolve` can share the request's own dependency cache — the same instances FastAPI built for the handler. Register `init_inject_scope` as a dependency:

```python
from fastapi import Depends, FastAPI
from fastapi_injected import Dep, init_inject_scope, resolve

app = FastAPI(dependencies=[Depends(init_inject_scope)])


@app.get("/")
async def route(service: Dep[Service]) -> str:
    same = await resolve(Service)  # same instance as `service`
    ...
```

Anything called from the handler — including `@inject`-ed helpers — resolves against the request's cache, so a per-request dependency like a DB session stays a single instance for the whole request.

## License

MIT
