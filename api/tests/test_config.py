from pathlib import Path

from app.config import PROJECT_ROOT, Settings, resolve_project_path


def test_relative_paths_resolve_against_project_root_not_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('CANVAS_DATA_DIR', './data')
    monkeypatch.delenv('CANVAS_DATABASE_PATH', raising=False)

    settings = Settings.from_env()

    assert settings.data_dir == PROJECT_ROOT / 'data'
    assert settings.database_path == PROJECT_ROOT / 'data' / 'canvas.sqlite3'


def test_api_and_worker_cwds_share_one_database(monkeypatch):
    monkeypatch.setenv('CANVAS_DATA_DIR', './data')
    monkeypatch.setenv('CANVAS_DATABASE_PATH', './data/canvas.sqlite3')

    monkeypatch.chdir(PROJECT_ROOT / 'api')
    api_settings = Settings.from_env()
    monkeypatch.chdir(PROJECT_ROOT)
    worker_settings = Settings.from_env()

    assert api_settings.database_path == worker_settings.database_path
    assert api_settings.data_dir == worker_settings.data_dir


def test_absolute_paths_are_kept(tmp_path):
    assert resolve_project_path(tmp_path / 'x.png') == tmp_path / 'x.png'
    assert resolve_project_path('data/assets/a.png') == PROJECT_ROOT / 'data/assets/a.png'
