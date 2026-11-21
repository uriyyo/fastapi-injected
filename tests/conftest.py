from collections.abc import Iterator

import pytest

from fastapi_injected import set_default_app


@pytest.fixture(autouse=True)
def _no_default_app() -> Iterator[None]:
    # `add_injection` sets it for whatever runs next
    with set_default_app(None):
        yield
