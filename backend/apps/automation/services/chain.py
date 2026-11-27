"""Контекст цепочки правил (PLAN-013, T-13022; SPEC-013, FR-806).

Глубина не больше 3; правило не выполняется повторно в своей цепочке.
"""
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace

MAX_DEPTH = 3
_ctx: ContextVar = ContextVar("automation_chain", default=None)


@dataclass(frozen=True)
class Chain:
    id: uuid.UUID
    depth: int
    rules: frozenset
    root_run_id: uuid.UUID | None = None


def start(subject_type: str, subject_id: int, *, root_run_id=None) -> object:
    """Начать цепочку; вернуть токен для `reset`."""
    return _ctx.set(Chain(uuid.uuid4(), 1, frozenset(), root_run_id))


def reset(token) -> None:
    _ctx.reset(token)


@contextmanager
def child(rule_id: int | None = None):
    """Войти в следующий уровень; правило помечается выполненным в цепочке."""
    current = _ctx.get()
    if current is None:
        yield None
        return
    rules = current.rules | ({rule_id} if rule_id is not None else set())
    token = _ctx.set(replace(current, depth=current.depth + 1, rules=frozenset(rules)))
    try:
        yield _ctx.get()
    finally:
        _ctx.reset(token)


def current() -> Chain | None:
    return _ctx.get()


def depth() -> int:
    chain = _ctx.get()
    return chain.depth if chain is not None else 0


def chain_id():
    chain = _ctx.get()
    return chain.id if chain is not None else None


def can_run(rule_id: int) -> bool:
    chain = _ctx.get()
    if chain is None:
        return True
    return chain.depth <= MAX_DEPTH and rule_id not in chain.rules


def mark(rule_id: int) -> None:
    chain = _ctx.get()
    if chain is not None and rule_id not in chain.rules:
        _ctx.set(replace(chain, rules=frozenset(chain.rules | {rule_id})))
