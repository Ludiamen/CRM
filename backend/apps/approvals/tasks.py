"""Минутное задание согласований (PLAN-014, T-14031)."""
from .services import notices, routes


def approvals_tick() -> int:
    done = notices.run_due()
    done += routes.drop_inactive()
    return done
