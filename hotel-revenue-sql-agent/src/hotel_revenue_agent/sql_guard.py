"""Read-only SQL guardrail.

Defence in depth, three layers:
1. Static checks here: one statement, SELECT/WITH only, no write/DDL/PRAGMA keywords,
   no references to SQLite internals. Comments and string literals are stripped first so
   ``SELECT '--DROP'`` is not a false positive and ``/* */DROP`` cannot hide.
2. A SQLite authorizer (see ``database.py``) that only allows reads of allowlisted tables.
3. A read-only connection (``mode=ro``) so even a guard bug cannot write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hotel_revenue_agent.errors import SQLGuardError

FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "REPLACE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "VACUUM",
    "REINDEX",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "UPSERT",
)
FORBIDDEN_IDENTIFIERS = (
    "SQLITE_MASTER",
    "SQLITE_SCHEMA",
    "SQLITE_TEMP_MASTER",
    "LOAD_EXTENSION",
    "WRITEFILE",
    "READFILE",
    "FTS3_TOKENIZER",
)
MAX_SQL_LENGTH = 5_000

_BLOCK_COMMENT = re.compile(r"/\*.*?(\*/|$)", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_STRING = re.compile(r"'(?:[^']|'')*'")
_QUOTED_IDENT = re.compile(r'"(?:[^"]|"")*"')
_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(FORBIDDEN_KEYWORDS + FORBIDDEN_IDENTIFIERS) + r")\b", re.IGNORECASE
)


@dataclass(frozen=True)
class GuardedSQL:
    original: str
    sql: str  # the statement to execute, wrapped with a row limit
    limit: int


def strip_noise(sql: str) -> str:
    """Remove string literals and comments, leaving only SQL structure for keyword scans."""
    no_strings = _STRING.sub("''", sql)
    no_block = _BLOCK_COMMENT.sub(" ", no_strings)
    return _LINE_COMMENT.sub(" ", no_block)


def check_sql(sql: str) -> str:
    """Validate ``sql`` and return the cleaned single statement. Raises SQLGuardError."""
    if not isinstance(sql, str) or not sql.strip():
        raise SQLGuardError("Empty SQL.", hint="Send a single SELECT statement.")
    if len(sql) > MAX_SQL_LENGTH:
        raise SQLGuardError(
            f"SQL is longer than {MAX_SQL_LENGTH} characters.",
            hint="Simplify the query or split the question.",
        )
    structure = strip_noise(sql).strip()
    statement = structure.rstrip(";").strip()
    if ";" in statement:
        raise SQLGuardError(
            "Multiple statements are not allowed.", hint="Send exactly one SELECT statement."
        )
    first_word = statement.split(None, 1)[0].upper() if statement else ""
    if first_word not in {"SELECT", "WITH"}:
        raise SQLGuardError(
            f"Only SELECT queries are allowed (got {first_word or 'nothing'}).",
            hint="This is a read-only analytics database.",
        )
    # Scan with double-quoted identifiers stripped too, but also scan them on their own so a
    # quoted "sqlite_master" cannot slip through.
    match = _KEYWORD_RE.search(_QUOTED_IDENT.sub('""', statement)) or _KEYWORD_RE.search(
        " ".join(m.strip('"') for m in _QUOTED_IDENT.findall(statement))
    )
    if match:
        raise SQLGuardError(
            f"Forbidden keyword or object: {match.group(1).upper()}.",
            hint="Only read queries over the business tables are permitted.",
        )
    # Return the original text (literals intact) minus trailing semicolons.
    return sql.strip().rstrip(";").strip()


def guard(sql: str, max_rows: int) -> GuardedSQL:
    """Validate and wrap the statement so at most ``max_rows + 1`` rows come back.

    The extra row lets the caller report truncation without a separate COUNT query.
    """
    cleaned = check_sql(sql)
    wrapped = f"SELECT * FROM (\n{cleaned}\n) LIMIT {int(max_rows) + 1}"
    return GuardedSQL(original=sql, sql=wrapped, limit=max_rows)
