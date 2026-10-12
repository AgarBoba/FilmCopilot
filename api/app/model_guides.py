"""Model guides: models/<id>.md beside each models/<id>.json, in plain words for the agent.

The JSON says what the program needs ("can it": fields, limits, price, checks). The guide says
what the agent needs to plan well ("is it good at": strengths, weaknesses, input limits in
words, how to write prompts, known problems). Fixed headings, so tools can pull one section:

    # 模型名
    一两句介绍
    ## 擅长
    ## 不擅长
    ## 输入限制
    ## 提示词        a line `技能：<plugin>:<name>` names a prompt skill to load first
    ## 已知问题

models/_capabilities.md is the word list for the JSON's `capabilities`, one table row each.
"""
from dataclasses import dataclass, field
from pathlib import Path
import re

SECTIONS = ('擅长', '不擅长', '输入限制', '提示词', '已知问题')
CAPABILITIES_FILE = '_capabilities.md'
_SKILL_LINE = re.compile(r'^\s*[-*]?\s*技能\s*[:：]\s*`?([\w.-]+:[\w.-]+|[\w.-]+)`?\s*$', re.MULTILINE)


@dataclass(frozen=True)
class ModelGuide:
    text: str
    intro: str
    sections: dict[str, str] = field(default_factory=dict)
    skill: str | None = None
    missing: tuple[str, ...] = ()  # fixed headings the file doesn't have

    def section(self, name: str) -> str:
        return self.sections.get(name, '')

    def summary(self, name: str, limit: int = 120) -> str:
        """A section squeezed onto one line, for list_models."""
        text = _SKILL_LINE.sub('', self.section(name))
        items = [re.sub(r'^\s*[-*]\s*', '', line).strip() for line in text.splitlines()]
        line = '；'.join(item.rstrip('。；;') for item in items if item)
        return line if len(line) <= limit else line[:limit] + '…'


def parse_guide(text: str) -> ModelGuide:
    intro_lines: list[str] = []
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        heading = re.match(r'^##\s+(.+?)\s*$', line)
        if heading:
            current = sections.setdefault(heading.group(1), [])
            continue
        if line.startswith('# '):
            continue
        (current if current is not None else intro_lines).append(line)
    joined = {name: '\n'.join(lines).strip() for name, lines in sections.items()}
    skill_match = _SKILL_LINE.search(joined.get('提示词', ''))
    return ModelGuide(
        text=text,
        intro='\n'.join(intro_lines).strip(),
        sections=joined,
        skill=skill_match.group(1) if skill_match else None,
        missing=tuple(name for name in SECTIONS if name not in joined),
    )


@dataclass(frozen=True)
class Capability:
    name: str
    meaning: str
    tips: str


def parse_capabilities(text: str) -> dict[str, Capability]:
    """Rows of the markdown table in _capabilities.md (header and separator rows skipped)."""
    found: dict[str, Capability] = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')] if line.strip().startswith('|') else []
        if len(cells) < 2 or not re.fullmatch(r'[a-z][a-z0-9_]*', cells[0]):
            continue
        found[cells[0]] = Capability(cells[0], cells[1], cells[2] if len(cells) > 2 else '')
    return found


def read_capabilities(directory: Path) -> tuple[dict[str, Capability], str]:
    path = directory / CAPABILITIES_FILE
    if not path.exists():
        return {}, ''
    text = path.read_text(encoding='utf-8')
    return parse_capabilities(text), text
