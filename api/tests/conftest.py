from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.repositories import CanvasRepository


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / 'canvas.sqlite3',
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def repository(tmp_path) -> CanvasRepository:
    database = Database(tmp_path / 'repository.sqlite3')
    database.init_schema()
    return CanvasRepository(database)
