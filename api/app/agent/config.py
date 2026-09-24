"""Agent settings read from the environment (.env is loaded by scripts/dev.sh).

Two ways to pay for the model (AGENT_AUTH):
- api:          ANTHROPIC_API_KEY, billed per use.
- subscription: your Claude plan's usage (Pro / Max / Team / Enterprise), through the Claude
                Code login that the Agent SDK runs on. Use a long-lived token from
                `claude setup-token` in CLAUDE_CODE_OAUTH_TOKEN, or an existing `claude` login.
                Personal use only: a plan's usage may not power a product for other people.
                An API key in the environment would take precedence, so in this mode it is
                removed from the agent's environment.
Secrets are never read or logged here, only whether they are set.
"""
from dataclasses import dataclass
import os

# Models offered in the panel, strongest first. The first is the fallback default.
MODELS: tuple[tuple[str, str], ...] = (
    ('claude-opus-5-5', 'Opus 5.5'),
    ('claude-sonnet-5', 'Sonnet 5'),
    ('claude-haiku-4-5-20251001', 'Haiku 4.5'),
)
MODEL_IDS = tuple(model_id for model_id, _ in MODELS)
AUTH_MODES = ('api', 'subscription')


@dataclass(frozen=True)
class AgentConfig:
    model: str = 'claude-opus-5-5'
    api_key_present: bool = False
    auth: str = 'api'
    oauth_token_present: bool = False
    image_max_side: int = 1024
    image_wait_seconds: float = 300
    video_wait_seconds: float = 900
    poll_seconds: float = 2
    confirmation_timeout_seconds: float = 600

    @property
    def configured(self) -> bool:
        """Whether a message can be sent. With a subscription we can't see a plain `claude`
        login from here, so it counts as configured and a failed login is explained at run time."""
        return self.api_key_present if self.auth == 'api' else True

    @classmethod
    def from_env(cls) -> 'AgentConfig':
        api_key = bool(os.getenv('ANTHROPIC_API_KEY'))
        token = bool(os.getenv('CLAUDE_CODE_OAUTH_TOKEN'))
        auth = (os.getenv('AGENT_AUTH') or '').strip().lower()
        if auth not in AUTH_MODES:
            auth = 'subscription' if token and not api_key else 'api'
        model = os.getenv('AGENT_MODEL') or MODEL_IDS[0]
        return cls(model=model, api_key_present=api_key, auth=auth, oauth_token_present=token)


def explain_error(text: str, auth: str) -> str:
    """Turn a raw model / CLI error into one line the user can act on."""
    raw = str(text or '')
    lowered = raw.lower()
    if any(word in lowered for word in ('usage limit', 'rate limit', 'rate_limit', '429', 'limit reached', 'quota')):
        if auth == 'subscription':
            return ('Claude 订阅额度用完了（或暂时被限速）。等额度恢复后再试；急用的话把 .env 里的 '
                    'AGENT_AUTH 改成 api 并重启，改用 API Key 按量计费。')
        return 'Anthropic API 触发了速率限制，稍等一会儿再试。'
    if any(word in lowered for word in ('overloaded', '529')):
        return 'Anthropic 服务现在比较忙，稍后再试。'
    if any(word in lowered for word in ('401', '403', 'authentication', 'unauthorized', 'invalid x-api-key',
                                         'oauth', 'not logged in', 'invalid api key')):
        if auth == 'subscription':
            return ('Claude 订阅登录无效：在终端运行 claude setup-token，把得到的令牌填进 .env 的 '
                    'CLAUDE_CODE_OAUTH_TOKEN，然后重启 dev.sh。')
        return 'Anthropic API 认证失败：检查 .env 里的 ANTHROPIC_API_KEY 和网络代理。'
    return raw
