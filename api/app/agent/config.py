"""Agent settings read from the environment (.env is loaded by scripts/dev.sh)."""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class AgentConfig:
    model: str = 'claude-opus-5-5'
    api_key_present: bool = False
    image_max_side: int = 1024
    image_wait_seconds: float = 300
    video_wait_seconds: float = 900
    poll_seconds: float = 2
    confirmation_timeout_seconds: float = 600

    @classmethod
    def from_env(cls) -> 'AgentConfig':
        # The key itself is read by the SDK from the environment; we only record that it exists.
        return cls(
            model=os.getenv('AGENT_MODEL') or 'claude-opus-5-5',
            api_key_present=bool(os.getenv('ANTHROPIC_API_KEY')),
        )
