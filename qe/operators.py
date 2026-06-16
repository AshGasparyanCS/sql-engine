"""Physical operators (Volcano / iterator model). Each operator exposes
execute() -> iterator of rows, and describe() for EXPLAIN output."""
from __future__ import annotations

from .ast import Star
from .catalog import Table, evaluate, resolve_column


class Operator:
    est_rows: float = 0.0
    est_cost: float = 0.0

    def execute(self):  # -> Iterator[dict]
        raise NotImplementedError

    def describe(self, indent: int = 0) -> str:
        raise NotImplementedError


class Scan(Operator):
    def __init__(self, table: Table, alias: str):
        self.table = table
        self.alias = alias
        self.est_rows = table.row_count
        self.est_cost = table.row_count

    def execute(self):
        a = self.alias
        for r in self.table.rows:
            yield {f"{a}.{c}": r[c] for c in self.table.columns}

    def describe(self, indent=0):
        return "  " * indent + f"Scan {self.table.name} AS {self.alias} (rows≈{int(self.est_rows)})"


class Filter(Operator):
    def __init__(self, child: Operator, predicates: list, selectivity: float = 0.3):
        self.child = child
        self.predicates = predicates
        self.est_rows = child.est_rows * (selectivity ** len(predicates))
        self.est_cost = child.est_cost + child.est_rows

    def execute(self):
        for row in self.child.execute():
            if all(evaluate(p, row) for p in self.predicates):
                yield row

    def describe(self, indent=0):
        s = "  " * indent + f"Filter (rows≈{int(self.est_rows)})\n"
        return s + self.child.describe(indent + 1)


class NestedLoopJoin(Operator):
    def __init__(self, left: Operator, right: Operator, lkey, rkey):
        self.left, self.right = left, right
        self.lkey, self.rkey = lkey, rkey
        self.est_rows = max(left.est_rows, right.est_rows)
        # O(|L| * |R|): every left row scans every right row.
        self.est_cost = left.est_cost + left.est_rows * right.est_rows

    def execute(self):
        right_rows = list(self.right.execute())
        for l in self.left.execute():
            lv = resolve_column(self.lkey, l)
            for r in right_rows:
                if lv == resolve_column(self.rkey, r):
                    yield {**l, **r}

    def describe(self, indent=0):
        s = "  " * indent + f"NestedLoopJoin {self.lkey.key()}={self.rkey.key()} (cost≈{int(self.est_cost)})\n"
        return s + self.left.describe(indent + 1) + "\n" + self.right.describe(indent + 1)


class HashJoin(Operator):
    def __init__(self, left: Operator, right: Operator, lkey, rkey):
        self.left, self.right = left, right
        self.lkey, self.rkey = lkey, rkey
        self.est_rows = max(left.est_rows, right.est_rows)
        # O(|L| + |R|): build a hash on the right, probe with the left.
        self.est_cost = left.est_cost + left.est_rows + right.est_rows

    def execute(self):
        table: dict = {}
        for r in self.right.execute():
            table.setdefault(resolve_column(self.rkey, r), []).append(r)
        for l in self.left.execute():
            for r in table.get(resolve_column(self.lkey, l), ()):
                yield {**l, **r}

    def describe(self, indent=0):
        s = "  " * indent + f"HashJoin {self.lkey.key()}={self.rkey.key()} (cost≈{int(self.est_cost)})\n"
        return s + self.left.describe(indent + 1) + "\n" + self.right.describe(indent + 1)


_AGG_INIT = {"count": 0, "sum": 0, "avg": 0, "min": None, "max": None}


class HashAggregate(Operator):
    def __init__(self, child: Operator, group_cols: list, aggregates: list):
        # aggregates: list of (func_name, arg Column|Star, output_key)
        self.child = child
        self.group_cols = group_cols
        self.aggregates = aggregates
        self.est_rows = max(1.0, child.est_rows ** 0.5)
        self.est_cost = child.est_cost + child.est_rows

    def execute(self):
        groups: dict = {}
        for row in self.child.execute():
            key = tuple(resolve_column(c, row) for c in self.group_cols)
            acc = groups.setdefault(key, {"_count": 0, "rows": [], "key": key})
            acc["_count"] += 1
            acc["rows"].append(row)
        for acc in groups.values():
            out = {}
            for gc, kv in zip(self.group_cols, acc["key"]):
                out[gc.key()] = kv
            for func, arg, okey in self.aggregates:
                out[okey] = self._compute(func, arg, acc["rows"])
            yield out

    @staticmethod
    def _compute(func, arg, rows):
        if func == "count":
            if isinstance(arg, Star):
                return len(rows)
            return sum(1 for r in rows if resolve_column(arg, r) is not None)
        vals = [resolve_column(arg, r) for r in rows if resolve_column(arg, r) is not None]
        if func == "sum":
            return sum(vals)
        if func == "avg":
            return sum(vals) / len(vals) if vals else None
        if func == "min":
            return min(vals) if vals else None
        if func == "max":
            return max(vals) if vals else None
        raise ValueError(func)

    def describe(self, indent=0):
        gs = ", ".join(c.key() for c in self.group_cols) or "(all)"
        s = "  " * indent + f"HashAggregate group=[{gs}]\n"
        return s + self.child.describe(indent + 1)


class Project(Operator):
    def __init__(self, child: Operator, columns: list):
        # columns: list of (source_key_or_None, output_name, value_fn)
        self.child = child
        self.columns = columns
        self.est_rows = child.est_rows
        self.est_cost = child.est_cost

    def execute(self):
        for row in self.child.execute():
            yield {name: fn(row) for name, fn in self.columns}

    def describe(self, indent=0):
        cols = ", ".join(name for name, _ in self.columns)
        s = "  " * indent + f"Project [{cols}]\n"
        return s + self.child.describe(indent + 1)


class Sort(Operator):
    def __init__(self, child: Operator, col, asc: bool):
        self.child, self.col, self.asc = child, col, asc
        self.est_rows = child.est_rows
        self.est_cost = child.est_cost + child.est_rows  # n log n ~ n here

    def execute(self):
        rows = list(self.child.execute())
        rows.sort(key=lambda r: _sort_key(r, self.col), reverse=not self.asc)
        yield from rows

    def describe(self, indent=0):
        d = "ASC" if self.asc else "DESC"
        s = "  " * indent + f"Sort {self.col.key()} {d}\n"
        return s + self.child.describe(indent + 1)


class Limit(Operator):
    def __init__(self, child: Operator, n: int):
        self.child, self.n = child, n
        self.est_rows = min(child.est_rows, n)
        self.est_cost = child.est_cost

    def execute(self):
        for i, row in enumerate(self.child.execute()):
            if i >= self.n:
                break
            yield row

    def describe(self, indent=0):
        return "  " * indent + f"Limit {self.n}\n" + self.child.describe(indent + 1)


def _sort_key(row, col):
    try:
        return resolve_column(col, row)
    except KeyError:
        # output rows from Project use plain names
        return row.get(col.name, row.get(col.key()))
