from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.repositories import CanvasRepository


def test_concurrent_creation_of_default_canvas_is_idempotent(
    repository: CanvasRepository, monkeypatch
):
    barrier = Barrier(2)
    fetchone = repository._fetchone

    def synchronized_lookup(query, parameters):
        result = fetchone(query, parameters)
        if query == 'SELECT id FROM canvases WHERE id = ?':
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(repository, '_fetchone', synchronized_lookup)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: repository.create_canvas('Canvas', 'default'), range(2)))

    assert [canvas.canvasId for canvas in results] == ['default', 'default']
    assert repository.get_snapshot('default').revision == 0
