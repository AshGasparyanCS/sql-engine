# sqlengine — a SQL query engine from scratch

A small but real SQL engine in pure Python (no dependencies): it lexes and parses
SQL, builds a query plan, executes it with Volcano-style operators (including
**hash join**, **nested-loop join**, and **aggregation**), and chooses between
plans with a **cost-based optimizer**.

## Pipeline

```
SQL text
  → lexer (ast.tokenize)         tokens
  → parser (recursive descent)   Select AST
  → planner / optimizer          physical operator tree
  → executor (Volcano iterators) rows
```

## Supported SQL

```sql
SELECT  <cols | * | agg(col)> [AS alias]
FROM    <table [alias]>
[JOIN   <table [alias]> ON <a.col = b.col>]*
[WHERE  <conditions with = != < > <= >= AND OR ( )>]
[GROUP BY <cols>]
[ORDER BY <col [ASC|DESC]>]
[LIMIT  <n>]
```

Aggregates: `COUNT(*)`, `COUNT(col)`, `SUM`, `AVG`, `MIN`, `MAX`.

## Operators (Volcano model)

Each operator is an iterator yielding rows: `Scan`, `Filter`, `NestedLoopJoin`,
`HashJoin`, `HashAggregate`, `Project`, `Sort`, `Limit`. Rows are dicts keyed by
qualified name (`alias.column`).

| Join | Cost | When |
|------|------|------|
| Nested-loop | O(\|L\| × \|R\|) | any join condition |
| Hash | O(\|L\| + \|R\|) | equi-joins (build a hash on one side, probe with the other) |

## Cost-based optimizer

Three optimizations, all visible in `EXPLAIN`:

1. **Predicate pushdown** — single-table `WHERE` conjuncts are pushed down onto
   the relevant scan, so rows are filtered *before* joining.
2. **Join ordering** — joins are applied smallest-relation-first (using catalog
   row-count stats) to keep intermediate results small.
3. **Join-algorithm selection** — the planner estimates nested-loop vs hash cost
   and picks the cheaper. For equi-joins hash wins, and the engine confirms it.

```
$ python -m qe.cli
sql> \explain SELECT u.name FROM users u JOIN orders o ON u.id = o.user_id WHERE u.age > 40
Project [u.name]
  HashJoin u.id=o.user_id (cost≈...)
    Filter (rows≈...)          <- pushed-down age filter
      Scan users AS u
    Scan orders AS o
```

## Benchmark

`python bench.py` (2,000 users ⋈ 20,000 orders), measured in the sandbox:

```
nested-loop join:   6658.1 ms  (20000 rows)
hash join:            46.8 ms  (20000 rows)
speedup:             142.4x  -> optimizer auto-picks hash join

predicate pushdown: 37.3 ms (no filter) -> 19.3 ms (filter pushed below join)
```

The 142× gap is exactly the O(n·m) vs O(n+m) difference the optimizer reasons
about from its cost model.

## Run it

```bash
python -m qe.cli          # interactive REPL with demo tables (users, orders)
python bench.py           # the benchmark above
pytest -q                 # 10 tests
```

## Tests

`test_engine.py` covers parsing, `WHERE` with AND/OR precedence, both join
algorithms producing identical results, `GROUP BY` with `COUNT/SUM/MIN/MAX/AVG`,
`ORDER BY`/`LIMIT`, that the optimizer picks hash join, and that filters are
pushed below joins.

## Layout

```
qe/ast.py        tokens + AST nodes
qe/parser.py     recursive-descent parser
qe/catalog.py    in-memory tables, stats, expression evaluation
qe/operators.py  Volcano physical operators
qe/planner.py    cost-based optimizer (pushdown, ordering, algo choice)
qe/engine.py     Database facade (execute / explain)
qe/cli.py        REPL
bench.py         join-algorithm + pushdown benchmark
```

## Limitations

Inner equi-joins only (no outer joins / non-equi join conditions); `HAVING`,
subqueries, and `DISTINCT` aren't implemented; statistics are row-counts with a
fixed selectivity constant rather than histograms. The architecture (logical AST
→ cost-based physical plan → iterator operators) is the same one real engines
use, so each of these is an additive extension rather than a rewrite.
