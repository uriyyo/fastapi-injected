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
- `Arg[T]` — keep a parameter out of the dependency graph even though its annotation is a dependency, so the caller supplies it. See [Caller-supplied arguments](#caller-supplied-arguments).
- `Injected` — a sentinel default that exists purely to make type checkers happy: without it they would complain about a missing argument at call sites. At runtime the parameter is always filled in by `@inject`.

Injected parameters mix freely with regular ones — pass your own arguments as usual and the rest is injected:

```python
@inject
async def add(a: int, b: int, *, service: Dep[Service] = Injected) -> int:
    ...


result = await add(1, 2)
```

### Caller-supplied arguments

A parameter is injected only if it is written as a dependency — `Dep[...]`, `DepFactory[...]`, an `Annotated[..., Depends(...)]` of your own, or a `Depends(...)` default. Everything else is left for the caller, annotation untouched: it is never handed to pydantic, so any type works with no marker at all.

```python
class Connection:  # not a pydantic-friendly type, and it does not have to be
    ...


@inject
async def handler(conn: Connection, *, service: Dep[Service] = Injected) -> None:
    ...


await handler(connection)
```

`Arg[...]` is for the opposite case — a parameter that *is* spelled as a dependency, in a function that wants it passed in instead:

```python
from fastapi_injected import Arg

type ServiceDep = Annotated[Service, Depends(get_service)]


@inject
async def handler(service: Arg[ServiceDep], *, session: Dep[Session] = Injected) -> None:
    ...


await handler(service)
```

`Arg[T]` is a no-op for type checkers — the parameter stays typed as `T` — and at runtime it tells `@inject` to keep this parameter out of the dependency graph.

Writing `Injected` as the default of a parameter that is not a dependency raises `NotADependencyError` at decoration time, since nothing would ever fill it in.

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

Use `@inject(new_scope=True)` to opt a function out of the surrounding scope and always get fresh dependencies. It builds them again, but stays in the request they are being built for, so request-bound dependencies keep resolving.

Outside of a request there is no request to resolve against, so the scope makes one up. It answers what a dependency usually reads — `method`, `url`, `headers`, `path_params`, `client`, `state` — with the values of a request nobody sent. The application is the one thing it cannot invent: pass it when a dependency reaches for `request.app`:

```python
async with push_inject_scope(app=app):
    await handler()  # `request.app.state` resolves as it does in a route
```

Without it, reading `request.app` raises a `KeyError` naming what is missing rather than a bare `'app'`.

Analysing a dependency is the expensive part of resolving one, so the result is cached — keyed by the dependency itself, not by whatever object carried it, so nothing that only passed through is kept alive. `clear_dependant_cache()` drops it, for long-lived processes and test suites that want the memory back.

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

An override block is a scope of its own: it caches what it builds, and that cache goes away with the block. The surrounding scope keeps what it had resolved before, and it stays visible — except for the overridden dependencies and anything built from them, which are resolved again under the override:

```python
async with push_inject_scope():
    real = await handler()  # dependencies cached here

    with push_overrides({Session: fake}):
        await handler()  # rebuilt with `fake`, everything else reused from the cache

    await handler()  # back to the cached, real dependencies
```

Overrides can also be handed to the scope directly, which is the same thing in one call:

```python
async with push_inject_scope({Session: fake}) as scope:
    await handler()

    with scope.override({Session: other}):  # nest freely
        await handler()
```

### Dependencies that are objects

Dependants are cached by the callable that resolves them, so a dependency that is an object — a class holding configuration, a parametrized resolver — has to be hashable to get there. A plain dataclass is not, and a frozen one still refuses as soon as it holds a list or a dict.

`MakeDataclass` is a base class that makes its subclasses dataclasses with a hash that always answers: by fields when they can be hashed, by identity when they cannot.

```python
from dataclasses import field
from fastapi_injected import MakeDataclass, resolve


class Settings(MakeDataclass):
    hosts: list[str] = field(default_factory=list)

    def __call__(self) -> list[str]:
        return self.hosts


await resolve(Settings(["a", "b"]))  # a plain dataclass would raise TypeError here
```

Every `dataclasses.dataclass` option is accepted as a class keyword and passed straight through:

```python
class Config(MakeDataclass, frozen=True, kw_only=True):
    retries: int = 3
```

### When resolution fails

A dependency can fail to resolve for the same reasons it would in a route — a missing header, a query parameter that does not validate. `DependencyResolutionError` carries those errors in the shape pydantic produced them, and turns into the response FastAPI would have returned:

```python
from fastapi_injected import DependencyResolutionError

try:
    await handler()
except DependencyResolutionError as exc:
    exc.errors  # [{'type': 'missing', 'loc': ('header', 'x-trace'), ...}]
    raise exc.as_validation_error() from exc  # a RequestValidationError, so a 422
```

It is a `ValueError`, which is what resolution used to raise, so code catching that keeps working.

### Dependencies decided at runtime

A dependency is usually written as an annotation, but sometimes it is a value a caller already has, or one picked while the program runs. `Given` turns a value into a dependency that resolves to it:

```python
from fastapi_injected import Given, resolve

doc = Doc(title="readme")

await resolve(Given(doc))  # the doc itself
```

Constants holding equal values are the same dependency, so they share a cache entry and can be overridden like any other. What `Given` returns is a marker held as a value — `DepOf[R]`, as opposed to `Dep[R]`, which is the same marker in annotation position.

`bind_deps` binds such markers to the leading parameters of a function, which is how a dependency graph gets built from markers that were not known when the function was written:

```python
from fastapi_injected import bind_deps

async def describe(doc: Doc, role: Role) -> str:
    return f"{doc.title}:{role.name}"


bound = bind_deps(describe, Given(doc), RoleDep)

await resolve(bound)  # "readme:admin", with `role` resolved as usual
```

What a parameter is bound to can be written any way a dependency can be: a marker like `Given(...)`, `Dep[T]` or `DepFactory[T, factory]`, a `Depends(...)`, or the callable itself — the same things `resolve` accepts.

Binding takes the parameters away, and a type checker sees what is left: `bind_deps(describe, Given(doc))` is a function of `(role)`, and binding both leaves one of no arguments at all. The bound function is a dependency like any other — resolve it, `@inject` it, override what it depends on. Binding more markers than the function has parameters is a `TypeError` rather than a silent truncation.

### Dependencies as objects

When the markers belong together, `MakeInjected` makes a dataclass of them: fields annotated with `DepOf` hold the markers, and the call receives what they resolve to.

```python
from fastapi_injected import Given, MakeInjected
from fastapi_injected.types import DepOf


class IsOwner(MakeInjected):
    doc: DepOf[Doc]
    role: DepOf[Role]
    loud: bool = False        # a plain field stays a plain field

    async def __call__(self, doc: Doc, role: Role) -> bool:
        return doc.owner == role.name


await resolve(IsOwner(doc=Given(doc), role=RoleDep))
```

It is a `MakeDataclass`, so instances built from equal markers are equal — and therefore one dependency, resolved once per scope and overridable as a whole. For callables that are not dataclasses, the two halves of the binding are available on their own: `signature_with_deps(func, deps)` builds the signature, and `remap_dep_args` turns the arguments it names back into positional ones.

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

## What is public

Everything the package supports is importable from `fastapi_injected` itself, and that is the surface a release keeps:

| | |
| --- | --- |
| Markers | `Dep`, `DepFactory`, `DepOf`, `Arg`, `Given`, `Injected` |
| Resolving | `inject`, `resolve`, `bind_deps`, `signature_with_deps`, `remap_dep_args`, `clear_dependant_cache` |
| Scopes and overrides | `InjectScope`, `push_inject_scope`, `inside_inject_scope`, `push_overrides`, `Overrides`, `OverridesProvider`, `ValueOverride`, `FactoryOverride` |
| Building on top | `MakeDataclass`, `MakeInjected`, `HasDependsHook`, `ArgMarker`, `is_arg`, `is_dep`, `unwrap_dep_tp`, `unwrap_dep_dependency` |
| FastAPI integration | `add_injected_scope`, `init_inject_scope` |
| Errors | `DependencyResolutionError`, `MissedDependencyError`, `MissingDependencyCacheError`, `NotADependencyError`, `UnboundDepArgsError`, `UnboundScopeError` |

`fastapi_injected.types` holds the typing vocabulary the signatures are written in — `DepReturn`, `DepShape`, `DepDecl`, `AsyncFunc`, `Coro` and friends — and is public too. Anything else, including every module whose name starts with an underscore, is machinery that can change in a patch release.

## License

MIT
