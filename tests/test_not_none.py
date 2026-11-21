from dataclasses import dataclass
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from fastapi_injected import Given, NotNone, add_injection, resolve

reads: list[int] = []


@dataclass
class Record:
    id: int


async def maybe_record(record_id: int) -> Record | None:
    reads.append(record_id)
    return Record(record_id) if record_id > 0 else None


type MaybeRecordDep = Annotated[Record | None, Depends(maybe_record)]
type RecordDep = NotNone[Record, MaybeRecordDep]


class GoneError(Exception):
    pass


def _app() -> FastAPI:
    app = FastAPI()
    add_injection(app)

    @app.get("/records/{record_id}")  # noqa: FAST003
    async def _get(record: RecordDep, again: RecordDep, maybe: MaybeRecordDep) -> int:
        assert record is again is maybe
        return record.id

    @app.exception_handler(GoneError)
    async def _gone(*_: object) -> None:
        raise HTTPException(410)

    @app.get("/gone/{record_id}")  # noqa: FAST003
    async def _gone_route(record: NotNone[Record, MaybeRecordDep, GoneError]) -> int:
        return record.id

    return app


def test_a_present_record_is_read_once_per_request() -> None:
    reads.clear()

    with TestClient(_app()) as client:
        assert client.get("/records/7").json() == 7

    assert reads == [7]


def test_a_missing_record_is_a_404() -> None:
    with TestClient(_app()) as client:
        assert client.get("/records/0").status_code == 404


def test_the_error_can_be_chosen() -> None:
    with TestClient(_app(), raise_server_exceptions=False) as client:
        assert client.get("/gone/0").status_code == 410


@pytest.mark.asyncio
async def test_not_none_is_one_dependency_per_source_dependency() -> None:
    assert NotNone[Record, MaybeRecordDep] == NotNone[Record, MaybeRecordDep]


@pytest.mark.asyncio
async def test_a_runtime_dependency_works_without_being_kept() -> None:
    assert await resolve(NotNone[Record, Given(Record(3))]) == Record(3)

    with pytest.raises(HTTPException) as exc_info:
        await resolve(NotNone[Record, Given(None)])

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_not_none_takes_a_type_and_a_dependency() -> None:
    with pytest.raises(TypeError, match="NotNone"):
        NotNone[Record]  # ty: ignore[invalid-type-form]
