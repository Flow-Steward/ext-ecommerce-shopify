"""A small reader for this extension's own fixed GraphQL documents.

The test dependencies are deliberately tiny (pytest, PyYAML and the SDK), so the
coverage checks cannot lean on a GraphQL library. The documents themselves are
small and regular: one operation, variables, fields with arguments, inline
fragments and the odd directive. This reads exactly that and refuses anything
else, so a document that grows a construct this file does not understand fails
loudly instead of being half-checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(
    r"""
    (?P<space>[\s,]+|\#[^\n]*)
  | (?P<spread>\.\.\.)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<number>-?\d+(?:\.\d+)?)
  | (?P<name>[_A-Za-z][_0-9A-Za-z]*)
  | (?P<punct>[{}()\[\]:!$=@])
    """,
    re.VERBOSE,
)


@dataclass
class Field:
    """One selected field: its name, the argument names it passes, its children."""

    name: str
    arguments: dict[str, str] = field(default_factory=dict)
    selections: list[Field] = field(default_factory=list)
    #: Inline fragments keyed by their type condition.
    fragments: dict[str, list[Field]] = field(default_factory=dict)


@dataclass
class Operation:
    kind: str
    name: str
    #: Variable name to its declared GraphQL type, for example ``"ID!"``.
    variables: dict[str, str]
    selections: list[Field]


def _tokens(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    position = 0
    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if match is None:
            raise ValueError(f"unreadable GraphQL near {text[position : position + 20]!r}")
        position = match.end()
        kind = match.lastgroup or ""
        if kind != "space":
            found.append((kind, match.group()))
    return found


class _Reader:
    def __init__(self, text: str) -> None:
        self.tokens = _tokens(text)
        self.index = 0

    def peek(self) -> str:
        return self.tokens[self.index][1] if self.index < len(self.tokens) else ""

    def take(self, expected: str | None = None) -> str:
        if self.index >= len(self.tokens):
            raise ValueError("unexpected end of GraphQL document")
        value = self.tokens[self.index][1]
        if expected is not None and value != expected:
            raise ValueError(f"expected {expected!r}, found {value!r}")
        self.index += 1
        return value

    def type_ref(self) -> str:
        if self.peek() == "[":
            self.take("[")
            inner = self.type_ref()
            self.take("]")
            text = f"[{inner}]"
        else:
            text = self.take()
        if self.peek() == "!":
            self.take("!")
            text += "!"
        return text

    def value_text(self) -> str:
        """Skip one argument value, returning its raw text."""
        start = self.index
        token = self.take()
        if token == "$":
            self.take()
        elif token in ("[", "{"):
            closing = "]" if token == "[" else "}"
            depth = 1
            while depth:
                current = self.take()
                if current == token:
                    depth += 1
                elif current == closing:
                    depth -= 1
        return " ".join(value for _kind, value in self.tokens[start : self.index])

    def arguments(self) -> dict[str, str]:
        found: dict[str, str] = {}
        if self.peek() != "(":
            return found
        self.take("(")
        while self.peek() != ")":
            name = self.take()
            self.take(":")
            found[name] = self.value_text()
        self.take(")")
        return found

    def directives(self) -> None:
        while self.peek() == "@":
            self.take("@")
            self.take()
            self.arguments()

    def selection_set(self) -> tuple[list[Field], dict[str, list[Field]]]:
        self.take("{")
        fields: list[Field] = []
        fragments: dict[str, list[Field]] = {}
        while self.peek() != "}":
            if self.peek() == "...":
                self.take("...")
                self.take("on")
                condition = self.take()
                inner, nested = self.selection_set()
                if nested:
                    raise ValueError("nested inline fragments are not supported")
                fragments[condition] = inner
                continue
            name = self.take()
            if self.peek() == ":":
                raise ValueError(f"aliases are not supported ({name})")
            entry = Field(name=name, arguments=self.arguments())
            self.directives()
            if self.peek() == "{":
                entry.selections, entry.fragments = self.selection_set()
            fields.append(entry)
        self.take("}")
        return fields, fragments


def parse(document: str) -> Operation:
    """Read one fixed operation document."""
    reader = _Reader(document)
    kind = reader.take()
    if kind not in ("query", "mutation"):
        raise ValueError(f"unsupported operation kind {kind!r}")
    name = reader.take()
    variables: dict[str, str] = {}
    if reader.peek() == "(":
        reader.take("(")
        while reader.peek() != ")":
            reader.take("$")
            variable = reader.take()
            reader.take(":")
            variables[variable] = reader.type_ref()
            if reader.peek() == "=":
                reader.take("=")
                reader.value_text()
        reader.take(")")
    reader.directives()
    selections, fragments = reader.selection_set()
    if fragments:
        raise ValueError("an operation cannot start with an inline fragment")
    if reader.peek():
        raise ValueError("one document holds exactly one operation")
    return Operation(kind=kind, name=name, variables=variables, selections=selections)


def named_type(type_ref: str) -> str:
    """``[ProductVariant!]!`` -> ``ProductVariant``."""
    return type_ref.replace("[", "").replace("]", "").replace("!", "")


__all__ = ["Field", "Operation", "named_type", "parse"]
