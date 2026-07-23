from product_image_batch.core.budget import BudgetManager


def test_no_cap_allows_everything():
    b = BudgetManager(max_total_cost=None)
    assert b.try_reserve(1000.0) is True
    assert b.max_total_cost is None


def test_zero_cap_means_no_cap():
    b = BudgetManager(max_total_cost=0.0)
    assert b.max_total_cost is None
    assert b.try_reserve(5.0) is True


def test_cap_blocks_over_budget():
    b = BudgetManager(max_total_cost=10.0)
    assert b.try_reserve(6.0) is True
    assert b.try_reserve(5.0) is False   # 6 + 5 > 10
    assert b.try_reserve(4.0) is True    # 6 + 4 == 10
    assert b.estimated_spend == 10.0


def test_release_returns_reservation():
    b = BudgetManager(max_total_cost=10.0)
    b.try_reserve(8.0)
    b.release(8.0)
    assert b.try_reserve(9.0) is True


def test_unknown_cost_flag():
    b = BudgetManager(max_total_cost=100.0)
    b.try_reserve(5.0, known=False)
    assert b.has_unknown_costs is True


def test_actual_spend_accumulates():
    b = BudgetManager()
    b.record_actual(1.5)
    b.record_actual(2.5)
    assert b.actual_spend == 4.0
