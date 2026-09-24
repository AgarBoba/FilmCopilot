import os

from app.agent.config import AgentConfig, explain_error


def test_auth_mode_from_env(monkeypatch):
    for name in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'AGENT_AUTH', 'AGENT_MODEL'):
        monkeypatch.delenv(name, raising=False)
    assert AgentConfig.from_env().auth == 'api' and not AgentConfig.from_env().configured
    monkeypatch.setenv('CLAUDE_CODE_OAUTH_TOKEN', 'tok')
    config = AgentConfig.from_env()
    assert config.auth == 'subscription' and config.configured and config.oauth_token_present
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'key')
    assert AgentConfig.from_env().auth == 'api'  # both set and no choice made: keep the old behaviour
    monkeypatch.setenv('AGENT_AUTH', 'Subscription')
    assert AgentConfig.from_env().auth == 'subscription'
    monkeypatch.delenv('CLAUDE_CODE_OAUTH_TOKEN')
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    assert AgentConfig.from_env().configured  # a plain `claude` login may exist; checked at run time
    monkeypatch.setenv('AGENT_MODEL', 'claude-sonnet-5')
    assert AgentConfig.from_env().model == 'claude-sonnet-5'


def test_errors_are_explained():
    assert '订阅额度' in explain_error('Claude AI usage limit reached|1790000000', 'subscription')
    assert 'setup-token' in explain_error('Invalid bearer token (401)', 'subscription')
    assert 'ANTHROPIC_API_KEY' in explain_error('authentication_error: invalid x-api-key', 'api')
    assert '比较忙' in explain_error('overloaded_error', 'api')
    assert explain_error('something else', 'api') == 'something else'
