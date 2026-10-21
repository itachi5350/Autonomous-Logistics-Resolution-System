import pytest

from app.sql_safety import UnsafeSQL, make_safe


def test_plain_select_is_wrapped_with_a_row_limit():
    assert make_safe("SELECT * FROM orders;").endswith("LIMIT 50")


@pytest.mark.parametrize("bad", [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "UPDATE orders SET amount_paid_inr = 0",
    "SELECT 1; DROP TABLE orders",
    "SELECT * FROM orders -- hi",
    "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
    "SELECT pg_sleep(10)",
])
def test_dangerous_sql_is_rejected(bad):
    with pytest.raises(UnsafeSQL):
        make_safe(bad)


def test_column_names_like_created_at_are_not_mistaken_for_keywords():
    make_safe("SELECT created_at, updated_at FROM cases")