"""Storage catalog and expression evaluation.

Tables are in-memory lists of dict rows. The catalog also tracks simple
statistics (row counts) that the cost-based optimizer uses to choose plans.
Rows flowing through operators are keyed by qualified name ("alias.column").
"""
from __future__ import annotations

from .ast import BinOp, Column, Literal


class Table:
    def __init__(self, name: str, columns: list[str], rows: list[dict]):
        self.name = name
        self.columns = columns
        self.rows = rows

    @property
    def row_count(self) -> int:
        return len(self.rows)


class Catalog:
    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}

    def add(self, name: str, columns: list[str], rows: list[dict]) -> None:
        self.tables[name] = Table(name, columns, rows)

    def get(self, name: str) -> Table:
        if name not in self.tables:
            raise KeyError(f"unknown table {name!r}")
        return self.tables[name]


def resolve_column(col: Column, row: dict):
    if col.table is not None:
        key = f"{col.table}.{col.name}"
        if key not in row:
            raise KeyError(f"unknown column {key}")
        return row[key]
    # unqualified: match the single column whose suffix is the name
    matches = [k for k in row if k.split(".")[-1] == col.name]
    if len(matches) == 1:
        return row[matches[0]]
    if col.name in row:
        return row[col.name]
    if not matches:
        raise KeyError(f"unknown column {col.name}")
    raise KeyError(f"ambiguous column {col.name}")


def evaluate(expr, row):
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, Column):
        return resolve_column(expr, row)
    if isinstance(expr, BinOp):
        op = expr.op
        if op == "and":
            return bool(evaluate(expr.left, row)) and bool(evaluate(expr.right, row))
        if op == "or":
            return bool(evaluate(expr.left, row)) or bool(evaluate(expr.right, row))
        left = evaluate(expr.left, row)
        right = evaluate(expr.right, row)
        if op == "=":
            return left == right
        if op in ("!=", "<>"):
            return left != right
        if op == "<":
            return left < right
        if op == ">":
            return left > right
        if op == "<=":
            return left <= right
        if op == ">=":
            return left >= right
        if op == "+":
            return left + right
        if op == "-":
            return left - right
    raise ValueError(f"cannot evaluate {expr!r}")


def referenced_tables(expr) -> set[str]:
    """Which table aliases an expression touches (for predicate pushdown)."""
    if isinstance(expr, Column):
        return {expr.table} if expr.table else set()
    if isinstance(expr, BinOp):
        return referenced_tables(expr.left) | referenced_tables(expr.right)
    return set()


def split_conjuncts(expr) -> list:
    """Flatten an AND-tree into a list of conjuncts for pushdown."""
    if expr is None:
        return []
    if isinstance(expr, BinOp) and expr.op == "and":
        return split_conjuncts(expr.left) + split_conjuncts(expr.right)
    return [expr]
