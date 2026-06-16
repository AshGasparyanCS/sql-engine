"""Recursive-descent parser. Operator precedence (low to high):
OR < AND < comparison < +/- < primary."""
from __future__ import annotations

from .ast import (
    AGGREGATES,
    BinOp,
    Column,
    FuncCall,
    Join,
    Literal,
    Projection,
    Select,
    Star,
    TableRef,
    Token,
    tokenize,
)


class Parser:
    def __init__(self, sql: str):
        self.toks = tokenize(sql)
        self.pos = 0

    # ---- token helpers ----
    def peek(self) -> Token:
        return self.toks[self.pos]

    def next(self) -> Token:
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def at_kw(self, *words: str) -> bool:
        t = self.peek()
        return t.kind == "KW" and t.value.lower() in words

    def eat_kw(self, word: str) -> None:
        t = self.next()
        if not (t.kind == "KW" and t.value.lower() == word):
            raise SyntaxError(f"expected {word!r}, got {t.value!r}")

    def eat(self, kind: str) -> Token:
        t = self.next()
        if t.kind != kind:
            raise SyntaxError(f"expected {kind}, got {t.kind} {t.value!r}")
        return t

    # ---- grammar ----
    def parse(self) -> Select:
        self.eat_kw("select")
        projections = self._projections()
        self.eat_kw("from")
        from_ = self._table_ref()

        joins = []
        while self.at_kw("join", "inner"):
            if self.at_kw("inner"):
                self.next()
            self.eat_kw("join")
            tbl = self._table_ref()
            self.eat_kw("on")
            left = self._column()
            op = self.eat("OP")
            if op.value != "=":
                raise SyntaxError("only equi-joins (col = col) are supported")
            right = self._column()
            joins.append(Join(tbl, left, right))

        where = None
        if self.at_kw("where"):
            self.next()
            where = self._or_expr()

        group_by = []
        if self.at_kw("group"):
            self.next(); self.eat_kw("by")
            group_by.append(self._column())
            while self.peek().kind == "COMMA":
                self.next(); group_by.append(self._column())

        order_by = None
        if self.at_kw("order"):
            self.next(); self.eat_kw("by")
            col = self._column()
            asc = True
            if self.at_kw("asc"):
                self.next()
            elif self.at_kw("desc"):
                self.next(); asc = False
            order_by = (col, asc)

        limit = None
        if self.at_kw("limit"):
            self.next()
            limit = int(self.eat("NUM").value)

        self.eat("EOF")
        return Select(projections, from_, joins, where, group_by, order_by, limit)

    def _projections(self) -> list[Projection]:
        projs = [self._projection()]
        while self.peek().kind == "COMMA":
            self.next()
            projs.append(self._projection())
        return projs

    def _projection(self) -> Projection:
        if self.peek().kind == "STAR":
            self.next()
            return Projection(Star())
        expr = self._proj_expr()
        alias = None
        if self.at_kw("as"):
            self.next()
            alias = self.eat("ID").value
        return Projection(expr, alias)

    def _proj_expr(self):
        # aggregate function or a column
        t = self.peek()
        if t.kind == "ID" and t.value.lower() in AGGREGATES and self.toks[self.pos + 1].kind == "LP":
            name = self.next().value.lower()
            self.eat("LP")
            if self.peek().kind == "STAR":
                self.next(); arg: object = Star()
            else:
                arg = self._column()
            self.eat("RP")
            return FuncCall(name, arg)
        return self._column()

    def _table_ref(self) -> TableRef:
        name = self.eat("ID").value
        alias = name
        if self.at_kw("as"):
            self.next()
            alias = self.eat("ID").value
        elif self.peek().kind == "ID":
            alias = self.next().value
        return TableRef(name, alias)

    def _column(self) -> Column:
        first = self.eat("ID").value
        if self.peek().kind == "DOT":
            self.next()
            col = self.eat("ID").value
            return Column(col, table=first)
        return Column(first)

    # WHERE expression grammar
    def _or_expr(self):
        left = self._and_expr()
        while self.at_kw("or"):
            self.next()
            left = BinOp("or", left, self._and_expr())
        return left

    def _and_expr(self):
        left = self._cmp_expr()
        while self.at_kw("and"):
            self.next()
            left = BinOp("and", left, self._cmp_expr())
        return left

    def _cmp_expr(self):
        left = self._add_expr()
        if self.peek().kind == "OP" and self.peek().value in {"=", "!=", "<>", "<", ">", "<=", ">="}:
            op = self.next().value
            right = self._add_expr()
            return BinOp("=" if op == "==" else op, left, right)
        return left

    def _add_expr(self):
        left = self._primary()
        while self.peek().kind == "OP" and self.peek().value in {"+", "-"}:
            op = self.next().value
            left = BinOp(op, left, self._primary())
        return left

    def _primary(self):
        t = self.peek()
        if t.kind == "LP":
            self.next()
            e = self._or_expr()
            self.eat("RP")
            return e
        if t.kind == "NUM":
            self.next()
            return Literal(float(t.value) if "." in t.value else int(t.value))
        if t.kind == "STR":
            self.next()
            return Literal(t.value)
        if t.kind == "ID":
            return self._column()
        raise SyntaxError(f"unexpected token {t.kind} {t.value!r}")


def parse(sql: str) -> Select:
    return Parser(sql).parse()
