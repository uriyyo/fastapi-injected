import email.message
import json
from contextlib import AsyncExitStack
from typing import Any

from fastapi import Request, params
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import _get_flat_body_params, _should_embed_body_fields
from fastapi.routing import APIRoute
from starlette.datastructures import FormData

from .types import BoundConnection

type RequestBody = tuple[Any, bool]


class InvalidBodyError(ValueError):
    def __init__(self, errors: list[Any], /) -> None:
        super().__init__(errors)
        self.errors = errors


def _is_json_content_type(content_type: str | None, /) -> bool:
    if not content_type:
        return False

    message = email.message.Message()
    message["content-type"] = content_type

    if message.get_content_maintype() != "application":
        return False

    subtype = message.get_content_subtype()
    return subtype == "json" or subtype.endswith("+json")


async def _read_form(request: Request, /) -> FormData:
    parsed = request._form is not None  # noqa: SLF001

    form = await request.form()

    if not parsed:
        stack: AsyncExitStack = request.scope["fastapi_middleware_astack"]
        stack.push_async_callback(form.close)

    return form


async def _read_body(request: Request, *, is_form: bool) -> Any:
    if is_form:
        return await _read_form(request)

    if not (body := await request.body()):
        return None

    if not _is_json_content_type(request.headers.get("content-type")):
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


def _body_shape(request: Request, dependant: Dependant, /) -> tuple[bool, bool] | None:
    route = request.scope.get("route")

    match route:
        case APIRoute(body_field=body_field) if body_field is not None:
            return (
                isinstance(body_field.field_info, params.Form),
                route._embed_body_fields,  # noqa: SLF001
            )

    if not (body_params := _get_flat_body_params(dependant)):
        return None

    is_form = any(isinstance(field.field_info, params.Form) for field in body_params)

    return is_form, _should_embed_body_fields(body_params)


async def request_body(request: BoundConnection, dependant: Dependant, /) -> RequestBody:
    if not isinstance(request, Request) or (shape := _body_shape(request, dependant)) is None:
        return None, False

    is_form, embed_body_fields = shape

    return (
        await _read_body(request, is_form=is_form),
        embed_body_fields,
    )


__all__ = [
    "InvalidBodyError",
    "request_body",
]
