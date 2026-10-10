"""Credits (积分): a simulated wallet, the first step toward letting other people use the canvas
without bringing their own API keys.

One wallet for the whole local install (there are no user accounts yet). Every change is a row
in `credit_ledger`; the balance is the newest row's `balance_after`.

What costs credits:
- a generation, charged when it is queued, at the price in its model file ("credits", below);
  given back if it fails or an agent undo cancels it before it starts;
- an agent turn, when it finishes, from what the model calls actually cost (1 积分 = US$0.01).
  Each turn records its exact usage (e.g. 2.23) for display; the balance only loses whole
  credits, and the leftover fraction is carried to the next turn (no rounding up per turn).
  A turn may take the balance a little below zero; the next one is refused until there are
  credits again.

Prices live in each models/*.json file:
    "credits": 4                                    # flat
    "credits": {"base": 30, "multiply": {"duration": {"10": 2}, "resolution": {"480p": 0.5}}}
The multipliers are looked up by parameter key, then by the chosen value written as text
(booleans as "true" / "false"); values not listed count as 1. The price is rounded up.
Models without a price use DEFAULT_PRICE for their kind.

Adding credits is manual for now (POST /api/credits/top-up, the 积分 button on the canvas).
"""
from __future__ import annotations

import math
from typing import Any, TYPE_CHECKING

from .db import Database
from .domain import DomainError

if TYPE_CHECKING:
    from .models_registry import ModelSpec

USD_PER_CREDIT = 0.01
WELCOME_CREDITS = 500
DEFAULT_PRICE = {'image': 5, 'video': 30}
MAX_TOP_UP = 100_000
KIND_LABELS = {
    'welcome': '新手赠送', 'top_up': '充值', 'generation': '生成', 'refund': '退回', 'chat': 'Agent 对话',
}


def price_spec(raw: Any, where: str) -> dict[str, Any] | None:
    """Check a model file's "credits" value; returns {base, multiply} or None when absent."""
    from .models_registry import ModelFileError

    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float, dict)):
        raise ModelFileError(f'{where}: "credits" 要写成数字，或 {{"base": N, "multiply": {{...}}}}')
    if not isinstance(raw, dict):
        raw = {'base': raw}
    base = raw.get('base')
    if isinstance(base, bool) or not isinstance(base, (int, float)) or base < 0:
        raise ModelFileError(f'{where}: credits.base 要是不小于 0 的数字')
    multiply = raw.get('multiply') or {}
    if not isinstance(multiply, dict) or not all(
        isinstance(table, dict) and all(
            not isinstance(factor, bool) and isinstance(factor, (int, float)) and factor >= 0
            for factor in table.values()
        )
        for table in multiply.values()
    ):
        raise ModelFileError(f'{where}: credits.multiply 要写成 {{"参数": {{"取值": 倍数}}}}')
    return {'base': base, 'multiply': {key: {str(k): v for k, v in table.items()} for key, table in multiply.items()}}


def _value_key(value: Any) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def generation_price(model: ModelSpec, parameters: dict[str, Any] | None = None) -> int:
    """Credits one generation with these parameters costs (defaults filled in)."""
    spec = model.credits or {'base': DEFAULT_PRICE.get(model.kind, 5), 'multiply': {}}
    resolved, _ = model.resolve_parameters(parameters)
    amount = float(spec['base'])
    for key, table in spec['multiply'].items():
        amount *= table.get(_value_key(resolved.get(key)), 1)
    return max(0, math.ceil(round(amount, 6)))


def chat_price(cost_usd: float | None) -> float:
    """What an agent turn that cost `cost_usd` in model calls used, in credits (exact, not rounded).
    The wallet is charged whole credits only; see Credits.charge_usage."""
    if not cost_usd or cost_usd <= 0:
        return 0.0
    return round(cost_usd / USD_PER_CREDIT, 4)


def price_text(model: ModelSpec) -> str:
    """For the agent: the default price and what changes it."""
    spec = model.credits or {'base': DEFAULT_PRICE.get(model.kind, 5), 'multiply': {}}
    parts = []
    for key, table in spec['multiply'].items():
        parts.extend(f'{key}={value} ×{factor:g}' for value, factor in table.items())
    extra = f'（{"，".join(parts)}）' if parts else ''
    return f'默认参数每次 {generation_price(model)} 积分{extra}'


def _balance(connection: Any) -> int:
    row = connection.execute('SELECT balance_after FROM credit_ledger ORDER BY id DESC LIMIT 1').fetchone()
    return int(row['balance_after']) if row else 0


def _owed(connection: Any) -> float:
    """Exact usage recorded minus whole credits taken for it: the carried fraction."""
    row = connection.execute(
        'SELECT COALESCE(SUM(amount), 0) AS used, COALESCE(SUM(-delta), 0) AS taken '
        'FROM credit_ledger WHERE amount IS NOT NULL').fetchone()
    return float(row['used']) - float(row['taken'])


class Credits:
    def __init__(self, database: Database) -> None:
        self.database = database

    def balance(self) -> int:
        with self.database.connection() as connection:
            return _balance(connection)

    def history(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                'SELECT id, delta, amount, kind, label, ref, balance_after, created_at FROM credit_ledger '
                'ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [
            {'id': row['id'], 'delta': row['delta'], 'kind': row['kind'], 'label': row['label'] or KIND_LABELS.get(row['kind'], ''),
             'ref': row['ref'], 'balanceAfter': row['balance_after'], 'createdAt': row['created_at'],
             # Agent turns: what the turn really used (delta is the whole credits taken from the balance).
             **({'used': row['amount']} if row['amount'] is not None else {})}
            for row in rows
        ]

    def pending(self) -> float:
        """Usage not yet taken from the balance (always under 1 credit)."""
        with self.database.connection() as connection:
            return round(_owed(connection), 4)

    def summary(self) -> dict[str, Any]:
        return {'balance': self.balance(), 'pending': self.pending(), 'entries': self.history(),
                'usdPerCredit': USD_PER_CREDIT}

    def charge_usage(self, used: float, kind: str, label: str, ref: str | None = None) -> tuple[int, int]:
        """Record exact usage (e.g. 2.23 credits for an agent turn) and take only whole credits from
        the balance; the fraction is carried and taken once it adds up to a whole one.
        Returns (whole credits taken now, balance after). May go below zero."""
        if used <= 0:
            return 0, self.balance()
        with self.database.connection() as connection:
            if ref is not None and connection.execute(
                    'SELECT 1 FROM credit_ledger WHERE kind = ? AND ref = ?', (kind, ref)).fetchone():
                return 0, _balance(connection)
            whole = math.floor(round(_owed(connection) + used, 6) + 1e-9)
            balance = _balance(connection) - whole
            connection.execute(
                'INSERT INTO credit_ledger (delta, amount, kind, label, ref, balance_after) VALUES (?, ?, ?, ?, ?, ?)',
                (-whole, used, kind, label, ref, balance))
            if self.database.active_connection() is None:
                connection.commit()
        return whole, balance

    def _add(self, delta: int, kind: str, label: str, ref: str | None) -> int:
        with self.database.connection() as connection:
            if ref is not None and connection.execute(
                    'SELECT 1 FROM credit_ledger WHERE kind = ? AND ref = ?', (kind, ref)).fetchone():
                return _balance(connection)  # already recorded (retries, double refunds)
            balance = _balance(connection) + delta
            connection.execute(
                'INSERT INTO credit_ledger (delta, kind, label, ref, balance_after) VALUES (?, ?, ?, ?, ?)',
                (delta, kind, label, ref, balance))
            if self.database.active_connection() is None:
                connection.commit()
        return balance

    def require(self, amount: int, what: str) -> None:
        balance = self.balance()
        if amount > 0 and balance < amount or amount == 0 and balance <= 0:
            need = f'需要 {amount}，' if amount else ''
            raise DomainError('INSUFFICIENT_CREDITS', f'积分不够{what}：{need}现在剩 {balance}。点左上角的积分充值。')

    def charge(self, amount: int, kind: str, label: str, ref: str | None = None, allow_negative: bool = False) -> int:
        if amount <= 0:
            return self.balance()
        if not allow_negative:
            self.require(amount, '')
        return self._add(-amount, kind, label, ref)

    def refund_job(self, job_id: str, reason: str) -> int:
        """Give back what a generation was charged (once), e.g. it failed or was cancelled."""
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT delta, label FROM credit_ledger WHERE kind = 'generation' AND ref = ?", (f'job:{job_id}',)).fetchone()
        if row is None or row['delta'] >= 0:
            return self.balance()
        return self._add(-row['delta'], 'refund', f"{reason} · {row['label']}", f'job:{job_id}')

    def top_up(self, amount: Any) -> int:
        if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= MAX_TOP_UP:
            raise DomainError('INVALID_PAYLOAD', f'充值数量要是 1 到 {MAX_TOP_UP} 的整数')
        return self._add(amount, 'top_up', '手动充值', None)
