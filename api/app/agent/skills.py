"""Skills for the canvas agent, and which Claude Code built-in tools it may use.

Skills are native Agent SDK skills (SKILL.md files), loaded as two local *plugins* instead
of through `setting_sources`: turning on the "project" source would also load the repo's
CLAUDE.md / AGENTS.md (written for colleagues' coding agents) and the "user" source would
pull in the person's own Claude Code skills. A plugin is just a folder the SDK is told about
explicitly, so only these load:

    agent-skills/                 built-in, ships with the repo     plugin "film-copilot"
    <data dir>/agent-skills/      the user's own, never in git        plugin "my-skills"

Each holds .claude-plugin/plugin.json and skills/<name>/SKILL.md. Skill ids are
"<plugin>:<name>". The display label is the first "# " heading of SKILL.md.

Skills change *how* the agent works; they can't widen what it may do: the agent has no file
or shell tools, and every canvas write still goes through permissions.decide.
"""
from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from ..config import PROJECT_ROOT, Settings

BUILTIN_PLUGIN = 'film-copilot'
USER_PLUGIN = 'my-skills'

SKILL_TOOL = 'Skill'
WEB_TOOLS = ('WebSearch', 'WebFetch')
# The SDK's to-do list (it replaced TodoWrite). TaskStop is left out: it stops background work.
TASK_TOOLS = ('TaskCreate', 'TaskUpdate', 'TaskList', 'TaskGet')
# Built-in tools the canvas agent gets. Never Read / Write / Edit / Bash / Glob / Grep: they
# could read .env (keys) or change project files; canvas data goes through our own tools.
BUILTIN_TOOLS = (SKILL_TOOL, *WEB_TOOLS, *TASK_TOOLS)

# Order in the / menu: the most common jobs first. Skills not listed follow, by name.
BUILTIN_ORDER = ('storyboard', 'prompt-craft', 'review', 'canvas-layout')
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')


@dataclass(frozen=True)
class SkillInfo:
    id: str            # "film-copilot:storyboard", what the SDK calls it
    plugin: str
    name: str
    label: str         # "分镜拆解"
    description: str   # when to use it (the model reads this to decide)
    source: str        # "builtin" | "user"
    path: Path

    def public(self) -> dict:
        return {'id': self.id, 'name': self.name, 'label': self.label,
                'description': self.description, 'source': self.source}


def builtin_dir() -> Path:
    return PROJECT_ROOT / 'agent-skills'


def user_dir() -> Path:
    return Settings.from_env().data_dir / 'agent-skills'


def ensure_plugin(directory: Path, name: str, description: str) -> Path:
    """Create the plugin skeleton if it's missing (the user's folder starts empty)."""
    manifest = directory / '.claude-plugin' / 'plugin.json'
    if not manifest.exists():
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({'name': name, 'version': '1.0.0', 'description': description},
                                       ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (directory / 'skills').mkdir(parents=True, exist_ok=True)
    return directory


def plugin_dirs() -> list[Path]:
    dirs = []
    if (builtin_dir() / '.claude-plugin' / 'plugin.json').exists():
        dirs.append(builtin_dir())
    dirs.append(ensure_plugin(user_dir(), USER_PLUGIN, 'Film Copilot：我自己的技能'))
    return dirs


def parse_skill_file(text: str) -> tuple[dict[str, str], str]:
    """(frontmatter fields, body). Only the simple `key: value` lines SKILL.md uses."""
    meta: dict[str, str] = {}
    body = text
    if text.startswith('---'):
        end = text.find('\n---', 3)
        if end != -1:
            for line in text[3:end].splitlines():
                key, sep, value = line.partition(':')
                if sep and key.strip():
                    meta[key.strip()] = value.strip().strip('"\'')
            body = text[end + 4:].lstrip('\n')
    return meta, body


def _read_plugin(directory: Path, plugin: str, source: str) -> list[SkillInfo]:
    skills = []
    for path in sorted((directory / 'skills').glob('*/SKILL.md')):
        meta, body = parse_skill_file(path.read_text(encoding='utf-8'))
        name = meta.get('name') or path.parent.name
        if not NAME_RE.match(name) or meta.get('disabled', '').lower() == 'true':
            continue
        heading = next((line[2:].strip() for line in body.splitlines() if line.startswith('# ')), '')
        skills.append(SkillInfo(
            id=f'{plugin}:{name}', plugin=plugin, name=name, label=heading or name,
            description=meta.get('description', ''), source=source, path=path,
        ))
    return skills


def discover() -> list[SkillInfo]:
    """Every skill the agent can use, built-in first."""
    skills = []
    if (builtin_dir() / 'skills').exists():
        rank = {name: index for index, name in enumerate(BUILTIN_ORDER)}
        skills += sorted(_read_plugin(builtin_dir(), BUILTIN_PLUGIN, 'builtin'),
                         key=lambda skill: (rank.get(skill.name, len(rank)), skill.name))
    skills += _read_plugin(ensure_plugin(user_dir(), USER_PLUGIN, 'Film Copilot：我自己的技能'), USER_PLUGIN, 'user')
    return skills


def find(skill_id: str | None) -> SkillInfo | None:
    return next((skill for skill in discover() if skill.id == skill_id), None)


def url_allowed(url: str) -> tuple[bool, str]:
    """WebFetch may read public web pages only: not this machine or the local network
    (the canvas API runs on localhost, and a fetched page must not reach it)."""
    try:
        parsed = urlparse(str(url or '').strip())
    except ValueError:
        return False, '网址格式不对'
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False, '只能读取 http / https 网页'
    host = parsed.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.lan', '.home')):
        return False, '不能读取本机或局域网地址'
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True, ''
    if not address.is_global:
        return False, '不能读取本机或局域网地址'
    return True, ''
