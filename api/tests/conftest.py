from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / 'canvas.sqlite3',
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
