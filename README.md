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

Like `@inject`, `resolve` accepts `new_ctx=True` to force a fresh context instead of reusing the surrounding one.

### Contexts and caching

By default every call to an injected function gets its own injection context: dependencies are built, cached within the call, and torn down when it returns. Wrap several calls in `injection_ctx()` to share one cache (and defer teardown to the end of the context):

```python
from fastapi_injected import injection_ctx

async with injection_ctx():
    a = await handler()  # dependencies built here
    b = await handler()  # same instances reused
# generator dependencies are torn down here
```

Use `@inject(new_ctx=True)` to opt a function out of the surrounding context and always get fresh dependencies. It builds them again, but stays in the request they are being built for, so request-bound dependencies keep resolving.

Outside of a request there is no request to resolve against, so the context makes one up. It answers what a dependency usually reads — `method`, `url`, `headers`, `path_params`, `client`, `state` — with the values of a request nobody sent. The application is the one thing it cannot invent: pass it when a dependency reaches for `request.app`:

```python
async with injection_ctx(app=app):
    await handler()  # `request.app.state` resolves as it does in a route
```

Without it, the context falls back to the default app — the last one given to `add_injection` (see [FastAPI request integration](#fastapi-request-integration)). With neither, reading `request.app` raises a `KeyError` naming what is missing rather than a bare `'app'`.

When a dependency reads more of the request than that — a header, a cookie, a query or path parameter, the body — describe the request with `synthetic_request` and hand it to the context:

```python
from fastapi_injected import injection_ctx, synthetic_request

request = synthetic_request(
    headers={"x-trace": "job-42"},
    cookies={"sid": "abc"},
    query_params={"page": "2"},
    path_params={"item_id": 7},
    body={"name": "readme"},  # sent as JSON; bytes and str are sent as they are
    app=app,
)

async with injection_ctx(request=request):
    await handler()  # `Header()`, `Cookie()`, `Query()`, `Path()` and `Body()` resolve from it
```

Analysing a dependency is the expensive part of resolving one, so the result is cached — keyed by the dependency itself, not by whatever object carried it, so nothing that only passed through is kept alive. Only dependencies written in source code are cached this way: functions and classes, and annotations built from them. One made at runtime — `Given(...)`, a `MakeInjected` or `bind_deps` result, an object that brings its own `Depends` — is analysed again on every resolve, and FastAPI never gets to keep it: what it carries is released with the resolve instead of living as long as the process. `clear_dependant_cache()` drops the cache, for long-lived processes and test suites that want the memory back.

### Values scoped to a context

`ContextValue` is a `ContextVar` that lives as long as an injection context - inside a route, as long as the request. `set` writes to the current context, `get` reads the nearest one that has it: a nested context sees the value, but what it sets stays in it.

```python
from fastapi_injected import ContextValue

tenant = ContextValue[str]("tenant", default="public")


def set_tenant(x_tenant: Annotated[str, Header()]) -> None:
    tenant.set(x_tenant)


@app.get("/", dependencies=[Depends(set_tenant)])
async def route() -> str:
    return tenant.get()  # this request's tenant
```

Without a default, `get` raises `LookupError` when nothing set it; `set` outside a context raises `NoInjectionContextError`.

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

A callable value is called to produce the dependency, as in FastAPI's `dependency_overrides`; anything else is injected as it is. Two wrappers make the intent explicit and cover the ambiguous cases:

- `ValueOverride(value)` — always inject `value`, even when it is itself callable (a class, a mock, a function object).
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

An override block is a context of its own: it caches what it builds, and that cache goes away with the block. The surrounding context keeps what it had resolved before, and it stays visible — except for the overridden dependencies and anything built from them, which are resolved again under the override.

Enter the block with `async with` for what it builds to be torn down when the block ends. A plain `with` cannot run async teardown, so generator dependencies first built inside it are torn down with the surrounding context instead:

```python
async with injection_ctx():
    async with push_overrides({Session: fake}):
        await handler()  # a generator dependency built here...
    # ...is torn down here

    with push_overrides({Session: fake}):
        await handler()
    # still open - torn down when `injection_ctx()` ends
```

Reuse of the surrounding cache works the same either way:

```python
async with injection_ctx():
    real = await handler()  # dependencies cached here

    with push_overrides({Session: fake}):
        await handler()  # rebuilt with `fake`, everything else reused from the cache

    await handler()  # back to the cached, real dependencies
```

Overrides can also be handed to the context directly, which is the same thing in one call:

```python
async with injection_ctx({Session: fake}) as ctx:
    await handler()

    with ctx.override({Session: other}):  # nest freely
        await handler()
```

For FastAPI's own `app.dependency_overrides`, `override_app(app, {dep: fake})` sets entries for a `with` block and restores the previous mapping afterwards, including entries added inside the block.

A route reads `app.dependency_overrides` on its own. Outside a request, a context only knows the application it is given: `injection_ctx(app=app)`, or a `request=` whose scope carries one, applies that app's overrides the way a route would, beneath the overrides passed to the context itself. A context given neither uses the default app, the last one given to `add_injection`, and applies none when there is no default.

### Dependencies that are objects

Resolved values are cached in their context by the callable that resolves them, so a dependency that is an object — a class holding configuration, a parametrized resolver — has to be hashable to get there. A plain dataclass is not, and a frozen one still refuses as soon as it holds a list or a dict.

`MakeDataclass` is a base class that makes its subclasses dataclasses with a hash that always answers: by fields when they can be hashed, by identity when they cannot.

```python
from dataclasses import field
from fastapi_injected import resolve
from fastapi_injected.ext import MakeDataclass


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

### Values that must be there

A dependency that loads something often returns `None` when it is missing. `NotNone[T, dep]` is what `dep` resolves to, or a 404 when that is `None`, and a type checker sees it as plain `T`:

```python
from typing import Annotated
from fastapi import Depends
from fastapi_injected import NotNone

type MaybeUserDep = Annotated[User | None, Depends(load_user)]
type UserDep = NotNone[User, MaybeUserDep]


@app.get("/users/{user_id}")
async def get_user(user: UserDep) -> User:
    return user  # never None here
```

A third item chooses the error: anything called with no arguments that returns an exception, such as an exception class — `NotNone[User, MaybeUserDep, UserGone]`.

`NotNone` reads the same dependency it wraps, so a handler can ask for `UserDep` and `MaybeUserDep` side by side and the user is still loaded once per request. A dependency made at runtime, like `Given(...)`, works too, and is not kept once its resolve is done.

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

A request marker is bound under a made-up parameter name, so it has to say what it reads: `Annotated[int, Path(alias="item_id")]` binds, while a bare `Path()`, `Query()`, `Header()` or `Cookie()` raises `UnnamedParamError` instead of reading a parameter no request carries.

### Dependencies as objects

When the markers belong together, `MakeInjected` makes a dataclass of them: fields annotated with `DepOf` hold the markers, and the call receives what they resolve to.

```python
from fastapi_injected import Given
from fastapi_injected.ext import MakeInjected
from fastapi_injected.types import DepOf


class IsOwner(MakeInjected):
    doc: DepOf[Doc]
    role: DepOf[Role]
    loud: bool = False        # a plain field stays a plain field

    async def __call__(self, doc: Doc, role: Role) -> bool:
        return doc.owner == role.name


await resolve(IsOwner(doc=Given(doc), role=RoleDep))
```

The call has to be an `async def`; a sync one raises `NotAsyncError`, as it does for `bind_deps` and `remap_dep_args`.

It is a `MakeDataclass`, so instances built from equal markers are equal — and therefore one dependency, resolved once per context and overridable as a whole. For callables that are not dataclasses, the two halves of the binding are available on their own: `signature_with_deps(func, deps)` builds the signature, and `remap_dep_args` turns the arguments it names back into positional ones.

### Objects that bring their own `Depends`

An object with a `__get_depends__()` method is resolved through the `Depends` it returns instead of its own call - by `resolve`, `as_depends`, `add_route_dependency` and `reflect`. The protocol is `fastapi_injected.types.HasDependsHook`:

```python
class Guarded:
    def __call__(self) -> None: ...

    def __get_depends__(self) -> params.Depends:
        return Depends(require_admin, use_cache=False)


await resolve(Guarded())  # resolves `require_admin`
```

### Inspecting annotations

`fastapi_injected.ext` holds a few helpers for code that needs to reason about `Dep[...]` annotations — building override maps, custom decorators, and the like:

- `is_dep(tp)` — whether `tp` is a `Dep`/`DepFactory` annotation.
- `unwrap_dep_tp(tp)` — the annotated type (`Any` for a bare `Dep`).
- `unwrap_dep_dependency(tp)` — the callable that resolves it: the factory for `DepFactory[T, factory]`, the type itself for `Dep[T]`.
- `is_request_param(tp)` — whether `tp` carries `Header()`, `Query()`, `Path()`, `Cookie()` or a body marker.
- `unwrap_tp(tp)` — the value of a PEP 695 `type` alias, through nested aliases.
- `annotated(tp, *metadata)` — `Annotated[tp, *metadata]` without typing's cache, which would keep runtime markers alive.
- `as_depends(dep)` — the `Depends` for a marker, a `__get_depends__` object or a callable (`DependsSource`).

### Reflecting on apps and dependency trees

`fastapi_injected.reflect` answers the questions tests and tooling keep asking about an app, without walking `Dependant` trees or `app.routes` by hand.

```python
from fastapi_injected.reflect import find_route, iter_api_routes, iter_calls, iter_security

# every APIRoute with its full path, through include_router, Mount and Host
for path, route in iter_api_routes(app):
    assert get_current_user in iter_calls(route.dependant), path

route = find_route(app, method="POST", path="/items")  # or name="create_item"

# security schemes a route (or any callable) pulls in, with their OAuth scopes
assert list(iter_security(route.dependant)) == [(bearer, ["items:write"])]
```

- `iter_dependant(root, *, mode="bfs" | "dfs")` — every `Dependant` under `root`, the root first.
- `iter_calls(root, *, expand=None)` — unique callables `root` depends on, the root itself excluded. `expand(call)` returns extra calls to report for callables that hold more dependencies than their signature shows, such as composite permissions.
- `iter_security(root)` — `(scheme, scopes)` for every `SecurityBase` in the tree.
- `find_dependant(root, call)` — the chain of dependants from the root down to `call`, for saying *through what* a dependency is reached.
- `iter_overridden(root, overrides)` — the calls an override map or collection replaces, including every dependant above a replaced one, which is what stops caching across an override.
- `iter_routes(app)` — `(path, route)` for every route, with mounts, hosts and included routers expanded and the path prefixed accordingly. `iter_api_routes` keeps only FastAPI's HTTP and websocket routes, and `find_route(app, *, method=, path=, name=)` returns the first one matching every given filter, raising `LookupError` otherwise. Websocket routes answer to the method `WEBSOCKET`.
- `iter_routes_where(app, pred)` — `(method, path, route)` for every route `pred` accepts, one entry per method. The usual authorization test is `iter_routes_where(app, lambda r: guard not in iter_calls(r.dependant))`.
- `iter_operations(app_or_schema)` and `operation_for(app_or_schema, method, path)` — walk the OpenAPI document by `(path, method, operation)` instead of indexing nested dicts.
- `iter_routers(app)` — `(prefix, router)` for the app's router and every router included or mounted under it.
- `match_route(app, request_or_scope)` — `(path_template, route)` for the route that would handle a request, through mounts, hosts and included routers; `None` when nothing matches. Useful in middleware, where `request.scope["route"]` is not set yet.
- `iter_params(root)` — `(dependant, kind, field)` for every path, query, header, cookie and body parameter in the tree.
- `response_type(route, *, strip=True)` — the route's response type, falling back to the endpoint's return annotation, with `Annotated` and `| None` stripped unless `strip=False`.
- `Signature`, in `fastapi_injected.signature`, is an `inspect.Signature` with operations for decorators and dependencies that need FastAPI to see parameters a function did not declare. `Signature.of(func_or_signature)` starts one; each operation returns a new `Signature`, and `.apply(func)` sets it on a function. `globalns=`/`localns=` add names its annotations need beyond the module of `func`, and `include_return=True` keeps the return annotation.
  - `.add(*parameters)` — extra keyword-only parameters before `**kwargs`; names already present are kept as they are.
  - `.drop(*names)` and `.update(name, **changes)` — drop parameters a wrapper consumes itself, or change one parameter's annotation, default or kind.
  - `.add_dep(name, dep, *, annotation=Any)` — a parameter FastAPI resolves with a `Depends`/`Security` marker or a callable.
  - `.prepend(*parameters)`, `.rename(old, new)` and `.returns(annotation)` — positional parameters at the front, a renamed parameter, a new return annotation.
  - `Signature.role(parameter)` — which `ParamRole` a parameter plays: `dep` for `Dep[...]` or a `Depends` default, `request` for `Header()`/`Query()`/..., `arg` for `Arg[...]`, `plain` otherwise. `.select(*roles)` yields the parameters with those roles; `.annotations` and `.defaults` are name-to-value mappings of what is declared.
  - `.wrap(func)` — a forwarder to `func`, async when `func` is, carrying this signature; `.apply(func)` sets the signature on `func` itself.
- `add_route_dependency(route, *deps)` — append dependencies to an `APIRoute` or `APIWebSocketRoute` that is already built, and rebuild what FastAPI derived from its dependencies. Call it before the route's router is included elsewhere: an included router keeps its own copy until its routes change.
- `add_lifespan(app_or_router, lifespan)` — run a lifespan inside the one already set, merging the state both yield, for libraries that need a startup step on an app they did not create.

`root` for the dependency helpers is a `Dependant`, a `Depends(...)` marker or a plain callable; `as_dependant` is the conversion they share. A plain callable is read the way FastAPI would, with `Injected` defaults treated as dependencies.

### Adding to the OpenAPI schema

`fastapi_injected.openapi` gives libraries one shared `app.openapi` to add to, instead of each replacing it. The schema is cached in `app.openapi_schema` and built again when routes change, or after `invalidate_openapi(app)`.

- `add_openapi_hook(app, hook)` — `hook(app, schema)` post-processes the schema, in the order hooks were added; it changes `schema` in place or returns a new one.
- `__doc_depends__(methods)` — dependencies a call resolves itself, documented for every route that has it anywhere in its dependency tree (`HasDocDepends`, `iter_doc_depends(route)`). `add_openapi(app)` enables it without a hook.

A custom `app.openapi` is kept, and hooks run on its result.

```python
add_openapi_hook(app, lambda app, schema: {**schema, "x-version": "1"})
```

### FastAPI request integration

Inside a FastAPI app, `@inject`-ed functions and `resolve` can share the request's own dependency cache — the same instances FastAPI built for the handler. Call `add_injection`: it adds `InjectionMiddleware`, which opens the context for the whole request and binds it to the route's connection once the route is found - before or after routers are included. FastAPI is patched by `add_injection` or `InjectionMiddleware`, not on import. Add it after your other middleware, so the context is open for them too:

```python
from fastapi import FastAPI
from fastapi_injected import Dep, add_injection, resolve

app = FastAPI()
add_injection(app)


@app.get("/")
async def route(service: Dep[Service]) -> str:
    same = await resolve(Service)  # same instance as `service`
    ...
```

`add_injection` also makes `app` the default app: a context opened without a request — a background job, a bot handler, a script — resolves against it, so `request.app` is that app and its `dependency_overrides` apply, as they would in a route. The last app given to `add_injection` wins. `set_default_app` sets it directly, and used with `with` puts the previous one back when the block ends:

```python
from fastapi_injected import set_default_app

set_default_app(worker_app)  # for the rest of the process

with set_default_app(test_app):  # only inside the block
    await job()
```

A `resolve()` failing inside a route answers with a 422, or closes a websocket: `add_injection` registers `dependency_resolution_handler` unless a handler for `DependencyResolutionError` exists or `handle_resolution_errors=False` is passed.

The default lives in a context variable, so it reaches the tasks started after it is set: set it at startup, not inside a task that other tasks will not see.

Anything called from the handler — including `@inject`-ed helpers — resolves against the request's cache, so a per-request dependency like a DB session stays a single instance for the whole request. The context is opened by a middleware, so `resolve` also works inside middleware added before it (before routing, `request.scope["route"]` and path params are not available yet).

WebSocket routes work the same way: the context is bound to the `WebSocket` instead of a `Request`, and dependencies that ask for one get it. A websocket handed to a dependency shares its handshake with the one the route received, so it can be talked through after the route has called `accept()`:

```python
async def notify(websocket: WebSocket) -> None:
    await websocket.send_json({"ready": True})


@app.websocket("/ws")
async def ws_route(websocket: WebSocket, service: Dep[Service]) -> None:
    await websocket.accept()
    await resolve(notify)  # sends through the connection the route accepted
```

Dependencies that take request parameters — `Header()`, `Cookie()`, `Query()`, `Path()`, and the body as `Body()`, `Form()`, `File()` or a pydantic model — resolve from the request the context is bound to, exactly as they would in the route:

```python
class Item(BaseModel):
    name: str


async def get_item(item: Item) -> Item:
    return item


@app.post("/items")
async def create(request: Request) -> str:
    item = await resolve(get_item)  # the request body, parsed as FastAPI would
    ...
```

A request parameter is a dependency of its own as well - resolve a marker, or an annotation carrying one, without writing a function around it. On its own it has no parameter name, so the marker says what to read; a marker without an alias raises `UnnamedParamError`:

```python
api_key = await resolve(Header(alias="x-api-key"))  # the raw header, as `Any`
page = await resolve(Annotated[int, Query(alias="page")])  # validated as `int`
item_id = await resolve(Annotated[int, Path(alias="item_id")])
item = await resolve(Annotated[Item, Body()])  # the whole body needs no name


@inject
async def handler(*, api_key: Annotated[str, Header()] = Injected) -> str:
    return api_key  # a parameter has a name - `x-api-key`, as FastAPI derives it
```

The body is read only when the resolved dependency declares one, and it is read once per request, shared with the route and every context nested in it. When the route itself declares a body, dependencies see it in the shape the route gave it: a route with several body parameters embeds them under their names, and a dependency reads its own from there.

`injection_ctx(request=...)` accepts either a `Request` or a `WebSocket`, and so does everything that reads `InjectionContext.request` — the union is `fastapi_injected.types.BoundConnection`.

## What is public

The root package is what you need to use the library, and the surface a release keeps:

| | |
| --- | --- |
| Markers | `Dep`, `DepFactory`, `Arg`, `Given`, `Injected` |
| Resolving | `inject`, `resolve`, `bind_deps`, `NotNone` |
| Contexts and overrides | `InjectionContext`, `injection_ctx`, `ContextValue`, `synthetic_request`, `set_default_app`, `push_overrides`, `override_app`, `ValueOverride`, `FactoryOverride` |
| FastAPI integration | `add_injection` |
| Errors | `DependencyResolutionError`, `NoInjectionContextError`, `NotADependencyError`, `UnboundContextError`, `UnnamedParamError` |

Code that builds on the library imports from the submodule that owns the piece. These are public too:

| Module | Names |
| --- | --- |
| `fastapi_injected.ext` | `MakeDataclass`, `MakeInjected`, `signature_with_deps`, `remap_dep_args`, `is_dep`, `is_arg`, `is_request_param`, `unwrap_dep_tp`, `unwrap_dep_dependency`, `unwrap_tp`, `strip_annotation`, `annotated`, `as_depends`, `DependsSource`, `clear_dependant_cache`, `ensure_injection_ctx`, `MissedDependencyError`, `NotAsyncError`, `UnboundDepArgsError` |
| `fastapi_injected.types` | `DepOf`, `ArgMarker`, `HasDependsHook`, and the typing vocabulary the signatures are written in — `DepReturn`, `DepShape`, `DepDecl`, `AsyncFunc`, `Coro`, `BoundConnection`, `DependencyCache` and friends |
| `fastapi_injected.overrides` | `Overrides`, `OverridesProvider`, `OverrideBlock` |
| `fastapi_injected.signature` | `Signature`, `ParamRole` |
| `fastapi_injected.fastapi` | `InjectionMiddleware`, `bind_injection_ctx`, `dependency_resolution_handler`, `install_dependency_cache`, `MissingDependencyCacheError` |
| `fastapi_injected.openapi` | `add_openapi_hook`, `add_openapi`, `invalidate_openapi`, `HasDocDepends`, `iter_doc_depends`, `OpenAPIHook` |
| `fastapi_injected.reflect` | `iter_dependant`, `iter_calls`, `iter_security`, `iter_params`, `find_dependant`, `iter_overridden`, `iter_routes`, `iter_api_routes`, `iter_routes_where`, `find_route`, `match_route`, `iter_routers`, `response_type`, `add_route_dependency`, `add_lifespan`, `iter_operations`, `operation_for`, `as_dependant` |

Anything else, including every module whose name starts with an underscore, is machinery that can change in a patch release.

## License

MIT
