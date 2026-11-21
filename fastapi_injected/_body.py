import email.message
import json
from typing import Any

from fastapi import Request, params
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from pydantic_core import PydanticUndefined as Undefined

from ._errors import InjectedError
from ._fastapi_compat import MIDDLEWARE_ASTACK_KEY, embed_body_fields, flat_body_params, should_embed_body_fields
from .types import BoundConnection

type RequestBody = tuple[Any, bool]

BODY_CACHE_KEY = "fastapi_injected_body"


class InvalidBodyError(InjectedError, ValueError):
    def __init__(self, errors: list[Any], /) -> None:
        super().__init__(errors)
        self.errors = errors


def _is_json_content_type(content_type: str, /) -> bool:
    message = email.message.Message()
    message["content-type"] = content_type
    subtype = message.get_content_subtype()

    return message.get_content_maintype() == "application" and (subtype == "json" or subtype.endswith("+json"))


async def _read_body(request: Request, *, is_form: bool) -> Any:
    if is_form:
        form = await request.form()
        # closing a form twice is harmless
        request.scope[MIDDLEWARE_ASTACK_KEY].push_async_callback(form.close)

        return form

    if not (body := await request.body()):
        return Undefined

    if not _is_json_content_type(request.headers.get("content-type", "")):
        return body

    try:
        return await request.json()
    except json.JSONDecodeError as exc:
        raise InvalidBodyError(
            [
                {
                    "type": "json_invalid",
                    "loc": ("body", exc.pos),
                    "msg": "JSON decode error",
                    "input": {},
                    "ctx": {"error": exc.msg},
                },
            ],
        ) from exc


def _route_embeds(request: Request, /) -> bool:
    match request.scope.get("route"):
        case APIRoute() as route:
            return embed_body_fields(route)
        case _:
            return False


async def request_body(request: BoundConnection, dependant: Dependant, /) -> RequestBody:
    if not isinstance(request, Request) or not (fields := flat_body_params(dependant)):
        return Undefined, False

    is_form = any(isinstance(field.field_info, params.Form) for field in fields)

    # parsed once per request
    cache: dict[bool, Any] = request.scope[BODY_CACHE_KEY]

    if is_form not in cache:
        cache[is_form] = await _read_body(request, is_form=is_form)

    # read the body the way the route does
    return cache[is_form], _route_embeds(request) or should_embed_body_fields(fields)


__all__ = [
    "BODY_CACHE_KEY",
    "InvalidBodyError",
    "request_body",
]
