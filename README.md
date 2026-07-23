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
- `Injected` — a sentinel default that exists purely to make type checkers happy: without it they would complain about a missing argument at call sites. At runtime the parameter is always filled in by `@inject`.

Injected parameters mix freely with regular ones — pass your own arguments as usual and the rest is injected:

```python
@inject
async def add(a: int, b: int, *, service: Dep[Service] = Injected) -> int:
    ...


result = await add(1, 2)
```

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
