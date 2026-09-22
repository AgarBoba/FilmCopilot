from dataclasses import dataclass
from typing import Literal


NodeType = Literal["image", "video", "note"]


@dataclass(frozen=True, slots=True)
class EdgeRecord:
    source_node_id: str
    target_node_id: str


class DomainError(Exception):
    """A user-correctable canvas domain error with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
