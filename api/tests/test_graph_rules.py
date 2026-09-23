import pytest

from app.domain import DomainError, EdgeRecord
from app.graph_rules import validate_connection, would_create_cycle


def test_image_to_video_is_valid():
    validate_connection("image", "video", "image-1", "video-1", [])


def test_video_to_image_is_rejected():
    with pytest.raises(DomainError, match="INVALID_CONNECTION"):
        validate_connection("video", "image", "video-1", "image-1", [])


def test_self_link_and_duplicate_are_rejected():
    with pytest.raises(DomainError, match="SELF_LINK"):
        validate_connection("image", "image", "image-1", "image-1", [])

    edges = [EdgeRecord("image-1", "image-2")]
    with pytest.raises(DomainError, match="DUPLICATE_EDGE"):
        validate_connection("image", "image", "image-1", "image-2", edges)


def test_cycle_detection_follows_directed_reference_edges():
    edges = [EdgeRecord("image-1", "video-1"), EdgeRecord("video-1", "video-2")]
    assert would_create_cycle(edges, "video-2", "image-1") is True


def test_note_feeds_image_and_video_but_has_no_input():
    validate_connection("note", "image", "note-1", "image-1", [])
    validate_connection("note", "video", "note-1", "video-1", [])
    for source in ("image", "video", "note"):
        with pytest.raises(DomainError, match="INVALID_CONNECTION"):
            validate_connection(source, "note", f"{source}-1", "note-2", [])
