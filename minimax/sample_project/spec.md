# Orders service specification — revision 1

## ORD-001: Existing listing and pagination
`sample_project/orders.py::list_orders` returns orders sorted by integer `id` ascending.
With status omitted or None, all orders remain eligible. Default offset=0, limit=20.
Apply offset and limit after any filtering. Never mutate the input list or its dictionaries.
Verify with `sample_project/tests/test_orders.py` regression tests.

## ORD-002: New exact status filter
Implement the reserved keyword argument `status` in `list_orders`.
Allowed values are `pending`, `paid`, and `cancelled`. Match exactly and case-sensitively.
Only orders whose `status` equals the requested value are eligible.
An order without a status does not match a requested filter, but stays eligible without a filter.
An unmatched status selection returns an empty list. Filter before pagination.
Verify with `sample_project/tests/test_orders.py` target tests.

## ORD-003: Invalid status
Reject every non-None value outside the allowed strings with ValueError,
including empty string, uppercase values, booleans, lists, and dictionaries.
Validation applies even to an empty order list.

## ORD-004: Existing input boundaries
offset must be a non-negative integer; limit must be an integer from 1 through 100.
Boolean offset and limit are invalid. Invalid values raise ValueError.
Empty input returns []; pagination beyond the end returns [].
