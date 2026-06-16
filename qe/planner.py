"""Logical-to-physical planning with a cost-based optimizer.

Optimizations applied:
  * predicate pushdown    — single-table WHERE conjuncts are pushed into scans
  * join ordering         — greedily join the smallest next relation first to
                            keep intermediate results small
  * join algorithm choice — compare estimated NestedLoop vs Hash cost and pick
                            the cheaper (hash wins for equi-joins, as expected)
"""
from __future__ import annotations

from collections import defaultdict

from .ast import Column, FuncCall, Star
from .catalog import Catalog, referenced_tables, resolve_column, split_conjuncts
from .operators import (
    Filter,
    HashAggregate,
    HashJoin,
    Limit,
    NestedLoopJoin,
    Operator,
    Project,
    Scan,
    Sort,
)

SELECTIVITY = 0.3  # assumed selectivity of one filter predicate


def _est_card(catalog: Catalog, ref, pushed: list) -> float:
    return catalog.get(ref.name).row_count * (SELECTIVITY ** len(pushed))


def build_plan(select, catalog: Catalog, force_join: str | None = None) -> Operator:
    refs = {select.from_.key: select.from_}
    for j in select.joins:
        refs[j.table.key] = j.table

    # ---- predicate pushdown ----
    pushable: dict[str, list] = defaultdict(list)
    residual: list = []
    for c in split_conjuncts(select.where):
        tabs = referenced_tables(c)
        if len(tabs) == 1:
            pushable[next(iter(tabs))].append(c)
        else:
            residual.append(c)

    def scan_for(ref) -> Operator:
        op: Operator = Scan(catalog.get(ref.name), ref.key)
        if pushable[ref.key]:
            op = Filter(op, pushable[ref.key])
        return op

    # ---- join ordering + algorithm selection ----
    plan = scan_for(select.from_)
    built = {select.from_.key}
    remaining = list(select.joins)

    while remaining:
        # choose the connectable join whose NEW relation is estimated smallest
        best_idx, best_card = None, float("inf")
        for idx, j in enumerate(remaining):
            new = _new_side(j, built)
            if new is None:
                continue
            card = _est_card(catalog, refs[new], pushable[new])
            if card < best_card:
                best_idx, best_card = idx, card
        if best_idx is None:
            raise ValueError("join graph is disconnected")
        j = remaining.pop(best_idx)
        new = _new_side(j, built)
        # orient keys: left = already-built side, right = new relation
        if j.left.table == new:
            lkey, rkey = j.right, j.left
        else:
            lkey, rkey = j.left, j.right
        right = scan_for(refs[new])

        nl = NestedLoopJoin(plan, right, lkey, rkey)
        hj = HashJoin(plan, right, lkey, rkey)
        if force_join == "nl":
            plan = nl
        elif force_join == "hash":
            plan = hj
        else:
            plan = hj if hj.est_cost <= nl.est_cost else nl
        built.add(new)

    if residual:
        plan = Filter(plan, residual)

    # ---- aggregation vs plain projection ----
    aggs = [p for p in select.projections if isinstance(p.expr, FuncCall)]
    if select.group_by or aggs:
        agg_specs = []
        for p in select.projections:
            if isinstance(p.expr, FuncCall):
                arg = p.expr.arg
                argkey = "*" if isinstance(arg, Star) else arg.key()
                okey = p.alias or f"{p.expr.name}({argkey})"
                agg_specs.append((p.expr.name, arg, okey))
        plan = HashAggregate(plan, list(select.group_by), agg_specs)
    else:
        if not any(isinstance(p.expr, Star) for p in select.projections):
            cols = []
            for p in select.projections:
                col: Column = p.expr
                name = p.alias or col.key()
                cols.append((name, (lambda r, c=col: resolve_column(c, r))))
            plan = Project(plan, cols)

    if select.order_by:
        plan = Sort(plan, select.order_by[0], select.order_by[1])
    if select.limit is not None:
        plan = Limit(plan, select.limit)
    return plan


def _new_side(join, built: set[str]) -> str | None:
    lt, rt = join.left.table, join.right.table
    if lt in built and rt not in built:
        return rt
    if rt in built and lt not in built:
        return lt
    return None
