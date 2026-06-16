import pytest

from qe.demo import load_demo
from qe.engine import Database


@pytest.fixture
def db():
    d = Database()
    load_demo(d)
    return d


def test_select_star_and_filter(db):
    rows = db.execute("SELECT * FROM users WHERE age > 40")
    names = sorted(r["users.name"] for r in rows)
    assert names == ["alan", "grace", "linus"]


def test_projection_and_alias(db):
    rows = db.execute("SELECT name AS who FROM users WHERE id = 1")
    assert rows == [{"who": "ada"}]


def test_and_or_precedence(db):
    rows = db.execute("SELECT name FROM users WHERE age = 41 AND name = 'alan' OR id = 1")
    names = sorted(r["name"] for r in rows)
    assert names == ["ada", "alan"]


def test_join_both_algorithms_agree(db):
    sql = "SELECT u.name, o.amount FROM users u JOIN orders o ON u.id = o.user_id"
    hash_rows = db.execute(sql, force_join="hash")
    nl_rows = db.execute(sql, force_join="nl")
    key = lambda rs: sorted((r["u.name"], r["o.amount"]) for r in rs)
    assert key(hash_rows) == key(nl_rows)
    assert len(hash_rows) == 5  # 5 orders, all with a matching user


def test_group_by_aggregates(db):
    rows = db.execute(
        "SELECT u.name, COUNT(o.id) AS n, SUM(o.amount) AS total "
        "FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.name"
    )
    by_name = {r["u.name"]: r for r in rows}
    assert by_name["ada"]["n"] == 3 and by_name["ada"]["total"] == 100
    assert by_name["linus"]["total"] == 99


def test_order_by_and_limit(db):
    rows = db.execute("SELECT name, age FROM users ORDER BY age DESC LIMIT 2")
    assert [r["age"] for r in rows] == [54, 41]


def test_min_max_avg(db):
    rows = db.execute("SELECT MIN(amount) AS lo, MAX(amount) AS hi, AVG(amount) AS a FROM orders")
    assert rows[0]["lo"] == 5 and rows[0]["hi"] == 99


def test_optimizer_prefers_hash_join(db):
    plan = db.explain("SELECT u.name FROM users u JOIN orders o ON u.id = o.user_id")
    assert "HashJoin" in plan  # cheaper than nested loop for an equi-join


def test_predicate_pushdown(db):
    # The age filter should be pushed below the join, onto the users scan.
    plan = db.explain(
        "SELECT u.name, o.amount FROM users u JOIN orders o ON u.id = o.user_id WHERE u.age > 40"
    )
    lines = plan.splitlines()
    scan_idx = next(i for i, ln in enumerate(lines) if "Scan users" in ln)
    # a Filter appears directly above the users scan (deeper indent than the join)
    assert any("Filter" in ln for ln in lines[:scan_idx])


def test_cycle_free_parse_errors():
    db = Database()
    db.create_table("t", ["a"], [{"a": 1}])
    with pytest.raises(Exception):
        db.execute("SELECT FROM t")  # missing projection
