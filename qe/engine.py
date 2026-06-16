"""Database facade: register tables, run queries, and EXPLAIN plans."""
from __future__ import annotations

from .catalog import Catalog
from .parser import parse
from .planner import build_plan


class Database:
    def __init__(self) -> None:
        self.catalog = Catalog()

    def create_table(self, name: str, columns: list[str], rows: list[dict]) -> None:
        self.catalog.add(name, columns, rows)

    def execute(self, sql: str, force_join: str | None = None) -> list[dict]:
        plan = build_plan(parse(sql), self.catalog, force_join)
        return list(plan.execute())

    def explain(self, sql: str, force_join: str | None = None) -> str:
        plan = build_plan(parse(sql), self.catalog, force_join)
        return plan.describe() + f"\nestimated total cost: {plan.est_cost:.0f}"
