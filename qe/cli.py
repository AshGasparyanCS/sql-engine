"""Tiny REPL: type SQL, or `\\explain <sql>` to see the chosen plan."""
import sys
from .engine import Database
from .demo import load_demo


def main() -> None:
    db = Database()
    load_demo(db)
    print("sqlengine REPL — demo tables: users, orders. Ctrl-D to exit.")
    print("try: SELECT u.name, COUNT(o.id) AS n FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.name")
    while True:
        try:
            line = input("sql> ").strip()
        except EOFError:
            break
        if not line:
            continue
        try:
            if line.lower().startswith("\\explain"):
                print(db.explain(line[len("\\explain"):].strip()))
            else:
                rows = db.execute(line)
                for r in rows[:50]:
                    print(r)
                print(f"({len(rows)} rows)")
        except Exception as e:  # noqa: BLE001
            print("error:", e)


if __name__ == "__main__":
    main()
