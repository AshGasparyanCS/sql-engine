"""Lexer and AST for the SQL subset:

  SELECT <cols | * | agg(col)>
  FROM <table [alias]>
  [JOIN <table [alias]> ON <a.col = b.col>]*
  [WHERE <condition>]
  [GROUP BY <cols>]
  [ORDER BY <col [ASC|DESC]>]
  [LIMIT <n>]
"""
from __future__ import annotations

from dataclasses import dataclass, field

KEYWORDS = {
    "select", "from", "where", "join", "inner", "on", "group", "by",
    "order", "asc", "desc", "limit", "and", "or", "as",
}
AGGREGATES = {"count", "sum", "avg", "min", "max"}


@dataclass
class Token:
    kind: str   # KW, ID, NUM, STR, OP, STAR, COMMA, DOT, LP, RP, EOF
    value: str


def tokenize(sql: str) -> list[Token]:
    s = sql
    i, n = 0, len(s)
    toks: list[Token] = []
    two = {"<=", ">=", "!=", "<>"}
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c == "*":
            toks.append(Token("STAR", "*")); i += 1; continue
        if c == ",":
            toks.append(Token("COMMA", ",")); i += 1; continue
        if c == ".":
            toks.append(Token("DOT", ".")); i += 1; continue
        if c == "(":
            toks.append(Token("LP", "(")); i += 1; continue
        if c == ")":
            toks.append(Token("RP", ")")); i += 1; continue
        if s[i:i + 2] in two:
            toks.append(Token("OP", s[i:i + 2])); i += 2; continue
        if c in "=<>+-/":
            toks.append(Token("OP", c)); i += 1; continue
        if c == "'" or c == '"':
            j = i + 1
            buf = []
            while j < n and s[j] != c:
                buf.append(s[j]); j += 1
            toks.append(Token("STR", "".join(buf))); i = j + 1; continue
        if c.isdigit() or (c == "." and i + 1 < n and s[i + 1].isdigit()):
            j = i
            while j < n and (s[j].isdigit() or s[j] == "."):
                j += 1
            toks.append(Token("NUM", s[i:j])); i = j; continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (s[j].isalnum() or s[j] == "_"):
                j += 1
            word = s[i:j]
            kind = "KW" if word.lower() in KEYWORDS else "ID"
            toks.append(Token(kind, word)); i = j; continue
        raise SyntaxError(f"unexpected character {c!r} at {i}")
    toks.append(Token("EOF", ""))
    return toks


# ---- AST ----

@dataclass
class Column:
    name: str
    table: str | None = None  # qualifier, e.g. "u" in u.id

    def key(self) -> str:
        return f"{self.table}.{self.name}" if self.table else self.name


@dataclass
class Literal:
    value: object


@dataclass
class Star:
    pass


@dataclass
class FuncCall:
    name: str            # count/sum/avg/min/max
    arg: Column | Star


@dataclass
class BinOp:
    op: str
    left: object
    right: object


@dataclass
class TableRef:
    name: str
    alias: str

    @property
    def key(self) -> str:
        return self.alias or self.name


@dataclass
class Join:
    table: TableRef
    left: Column
    right: Column  # equi-join: left = right


@dataclass
class Projection:
    expr: object       # Column | Star | FuncCall
    alias: str | None = None


@dataclass
class Select:
    projections: list[Projection]
    from_: TableRef
    joins: list[Join] = field(default_factory=list)
    where: object | None = None
    group_by: list[Column] = field(default_factory=list)
    order_by: tuple[Column, bool] | None = None  # (col, asc)
    limit: int | None = None
