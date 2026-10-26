"""One unchanged suite is executed against both snapshots."""
import copy
import json
from pathlib import Path
import pytest
from sample_project.orders import list_orders

@pytest.fixture
def orders():
    return json.loads((Path(__file__).parents[1] / "seed.json").read_text())

@pytest.mark.target
@pytest.mark.parametrize("status,expected", [("paid", [2, 3, 5]), ("pending", [1]), ("cancelled", [4])])
def test_exact_status(orders, status, expected):
    assert [o["id"] for o in list_orders(orders, status=status)] == expected

@pytest.mark.target
def test_filter_before_pagination(orders):
    assert [o["id"] for o in list_orders(orders, status="paid", offset=1, limit=1)] == [3]

@pytest.mark.target
def test_unmatched_filter():
    assert list_orders([{"id": 1, "status": "pending"}], status="paid") == []

@pytest.mark.target
@pytest.mark.parametrize("status", ["", "PAID", "unknown", True, 7, [], {}])
def test_invalid_status(status):
    with pytest.raises(ValueError):
        list_orders([], status=status)

@pytest.mark.target
def test_missing_status_is_not_a_match():
    assert list_orders([{"id": 1}, {"id": 2, "status": "paid"}], status="paid") == [{"id": 2, "status": "paid"}]

@pytest.mark.target
def test_filter_does_not_mutate(orders):
    before = copy.deepcopy(orders)
    list_orders(orders, status="paid")
    assert orders == before

@pytest.mark.regression
def test_existing_listing(orders):
    assert [o["id"] for o in list_orders(orders)] == [1, 2, 3, 4, 5, 6]
    assert list_orders(orders, status=None) == list_orders(orders)

@pytest.mark.regression
def test_existing_pagination(orders):
    assert [o["id"] for o in list_orders(orders, offset=2, limit=2)] == [3, 4]
    assert list_orders(orders, offset=100) == []

@pytest.mark.regression
def test_empty_and_default_limit():
    assert list_orders([]) == []
    assert len(list_orders([{"id": i} for i in range(30)])) == 20

@pytest.mark.regression
def test_input_is_unchanged(orders):
    before = copy.deepcopy(orders)
    list_orders(orders)
    assert orders == before

@pytest.mark.regression
@pytest.mark.parametrize("offset", [-1, True, 1.5, "1"])
def test_invalid_offset(offset):
    with pytest.raises(ValueError):
        list_orders([], offset=offset)

@pytest.mark.regression
@pytest.mark.parametrize("limit", [0, 101, False, 1.5, "2"])
def test_invalid_limit(limit):
    with pytest.raises(ValueError):
        list_orders([], limit=limit)
