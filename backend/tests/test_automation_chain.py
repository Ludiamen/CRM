"""Красные контракты цепочки правил (T-13006; FR-806, FR-818)."""
import pytest

pytestmark = pytest.mark.django_db


def test_chain_depth_three_stops_and_same_rule_does_not_repeat():
    from apps.automation.services import chain

    token = chain.start("ticket", 1)
    try:
        assert chain.depth() == 1
        with chain.child():
            assert chain.depth() == 2
            with chain.child():
                assert chain.depth() == 3
                assert chain.can_run(1) is True
                with chain.child():
                    assert chain.depth() == 4
                    assert chain.can_run(1) is False
    finally:
        chain.reset(token)
