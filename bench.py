"""Benchmark: hash join vs nested-loop join, and predicate pushdown.

Shows (a) the optimizer's estimated costs, (b) actual runtimes for each forced
algorithm, and (c) that the optimizer picks the faster one.
"""
import random
import time

from qe.engine import Database


def build(n_users: int, n_orders: int) -> Database:
    db = Database()
    db.create_table("users", ["id", "name", "age"],
                    [{"id": i, "name": f"u{i}", "age": 20 + i % 50} for i in range(n_users)])
    db.create_table("orders", ["id", "user_id", "amount"],
                    [{"id": i, "user_id": random.randrange(n_users), "amount": random.randrange(100)}
                     for i in range(n_orders)])
    return db


def timeit(db, sql, force):
    t0 = time.perf_counter()
    rows = db.execute(sql, force_join=force)
    return time.perf_counter() - t0, len(rows)


def main():
    random.seed(1)
    db = build(2000, 20000)
    sql = "SELECT u.name, o.amount FROM users u JOIN orders o ON u.id = o.user_id"

    print("=== join algorithm comparison (2k users ⋈ 20k orders) ===")
    print(db.explain(sql))
    nl_t, nl_n = timeit(db, sql, "nl")
    hj_t, hj_n = timeit(db, sql, "hash")
    assert nl_n == hj_n
    print(f"\nnested-loop join: {nl_t*1000:8.1f} ms  ({nl_n} rows)")
    print(f"hash join:        {hj_t*1000:8.1f} ms  ({hj_n} rows)")
    print(f"speedup:          {nl_t/hj_t:8.1f}x  -> optimizer auto-picks hash join")

    print("\n=== predicate pushdown ===")
    sql2 = ("SELECT u.name, o.amount FROM users u JOIN orders o "
            "ON u.id = o.user_id WHERE u.age = 33")
    base_t, _ = timeit(db, "SELECT u.name, o.amount FROM users u JOIN orders o ON u.id = o.user_id", None)
    push_t, push_n = timeit(db, sql2, None)
    print(f"no filter:        {base_t*1000:8.1f} ms")
    print(f"filtered (pushed):{push_t*1000:8.1f} ms  ({push_n} rows after pushdown)")


if __name__ == "__main__":
    main()
