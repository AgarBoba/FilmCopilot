"""Layer 3 of the input rules: a provider refused a generation. Say why in plain words and keep it.

Providers phrase errors their own way ("Input image aspect ratio must be between 0.33 and 3",
"width must be divisible by 16"...). translate() turns the common ones into a sentence the
user and the agent can act on; anything unrecognised is passed through, shortened.
record() keeps each refusal in model_rejections, so the agent can see a model's unwritten
rules (get_model_guide lists the recent ones) and suggest adding them to models/<id>.md.
"""
from dataclasses import dataclass
import re
from typing import Any

# (kind, pattern, what to tell the user / agent). First match wins; patterns are lower-case.
_PATTERNS: list[tuple[str, str, str]] = [
    ('aspect_ratio', r'aspect[ _-]?ratio|宽高比|ratio .* between',
     '参考图的宽高比不符合这个模型的要求。先把参考图裁剪成常见比例再试，或换一个模型。'),
    ('dimension_multiple', r'(divisible|multiple) (by|of) \d+|倍数',
     '参考图的宽或高不是模型要求的倍数。把参考图裁剪成合适的尺寸再试。'),
    ('dimension', r'(width|height|resolution|dimension|pixels?)\b.*(too (small|large|big)|at least|at most|exceed|minimum|maximum|must be)|尺寸|分辨率',
     '参考图的尺寸不符合这个模型的要求（太小或太大）。换一张尺寸合适的参考图再试。'),
    ('file_size', r'file (is )?too large|file size|payload too large|413|文件过大',
     '参考文件太大了。压缩或换一个小一点的文件再试。'),
    ('duration', r'duration|too long|seconds|时长',
     '参考视频的时长不符合模型要求。剪短一些再试。'),
    ('too_many_inputs', r'too many|maximum (number|of \d+) (of )?(images|videos|inputs)|超过.*张',
     '参考数量超过了这个模型的上限。少连几个参考再试。'),
    ('prompt', r'prompt.*(too long|length|exceed|characters)|提示词.*(过长|长度)',
     'Prompt 太长了。删减一些再试。'),
    ('content_policy', r'nsfw|safety|sensitive|content (policy|moderation)|flagged|violat|审核|敏感',
     '内容审核没通过（Prompt 或参考图被判定为敏感）。换个说法，或换一张参考图再试。'),
    ('rate_limit', r'rate limit|429|too many requests|throttl',
     '模型服务暂时太忙（请求过多）。等一会儿再试。'),
    ('auth', r'unauthori[sz]ed|401|403|invalid (api )?(key|token)|authentication',
     '模型服务的密钥无效或没有权限。请检查 .env 里对应的密钥（跑 python3 scripts/doctor.py --online）。'),
    ('timeout', r'timed? ?out|timeout|deadline',
     '模型服务超时了。可以稍后重试。'),
]

# Kinds that mean "these inputs don't fit this model": worth writing into the model guide.
INPUT_KINDS = {'aspect_ratio', 'dimension_multiple', 'dimension', 'file_size', 'duration', 'too_many_inputs', 'prompt'}


@dataclass(frozen=True)
class Translated:
    kind: str
    message: str
    raw: str

    def text(self) -> str:
        """What the job (and so the node and the agent) shows: the plain sentence, then the original."""
        raw = self.raw if len(self.raw) <= 300 else self.raw[:300] + '…'
        if self.kind == 'other':
            return raw
        return f'{self.message}（原始报错：{raw}）'


def translate(raw: str) -> Translated:
    text = str(raw or '').strip() or '模型服务没有说明原因'
    lowered = text.lower()
    for kind, pattern, message in _PATTERNS:
        if re.search(pattern, lowered):
            return Translated(kind, message, text)
    return Translated('other', text, text)


def record(database: Any, model_id: str, job: dict[str, Any], translated: Translated) -> None:
    with database.connection() as connection:
        connection.execute(
            '''INSERT INTO model_rejections (model_id, canvas_id, node_id, job_id, kind, message, raw_error)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (model_id, job.get('canvas_id'), job.get('target_node_id'), job.get('id'),
             translated.kind, translated.message, translated.raw[:2000]))
        connection.commit()


def recent(database: Any, model_id: str, limit: int = 5) -> list[dict[str, Any]]:
    with database.connection() as connection:
        rows = connection.execute(
            '''SELECT kind, message, raw_error, created_at FROM model_rejections
               WHERE model_id = ? ORDER BY id DESC LIMIT ?''', (model_id, limit)).fetchall()
    return [dict(row) for row in rows]
