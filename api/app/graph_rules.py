from collections import defaultdict, deque
from collections.abc import Iterable

from .domain import DomainError, EdgeRecord, NodeType


_ALLOWED_CONNECTIONS: set[tuple[NodeType, NodeType]] = {
    ("image", "image"),
    ("image", "video"),
    ("video", "video"),
}


def would_create_cycle(
    edges: Iterable[EdgeRecord], source_id: str, target_id: str
) -> bool:
    """Return whether adding source_id -> target_id closes a directed cycle."""

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source_node_id].add(edge.target_node_id)

    pending = deque([target_id])
    visited: set[str] = set()
    while pending:
        node_id = pending.popleft()
        if node_id == source_id:
            return True
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(adjacency[node_id] - visited)
    return False


def validate_connection(
    source_type: NodeType,
    target_type: NodeType,
    source_id: str,
    target_id: str,
    edges: Iterable[EdgeRecord],
) -> None:
    """Validate one new reference edge, raising a stable DomainError on failure."""

    if not source_id or not target_id:
        raise DomainError("INVALID_NODE_ID", "Both connected nodes must have an id")
    if source_id == target_id:
        raise DomainError("SELF_LINK", "A node cannot reference itself")

    existing_edges = list(edges)
    if any(
        edge.source_node_id == source_id and edge.target_node_id == target_id
        for edge in existing_edges
    ):
        raise DomainError("DUPLICATE_EDGE", "This reference already exists")

    if (source_type, target_type) not in _ALLOWED_CONNECTIONS:
        raise DomainError(
            "INVALID_CONNECTION",
            f"A {source_type} node cannot reference a {target_type} node",
        )

    if would_create_cycle(existing_edges, source_id, target_id):
        raise DomainError("CYCLE", "Reference connections cannot form a cycle")
