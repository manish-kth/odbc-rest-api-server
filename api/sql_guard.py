"""Read-only gate for raw SQL sent with the read API key.

`ensure_read_only_sql` lets a single SELECT (or WITH ... SELECT) through
and rejects everything else. It fails closed: anything it cannot classify
with certainty is refused, so some harmless statements are rejected too
(for example one containing a SQL comment).

This is a filter, not a sandbox. It cannot see inside functions or stored
procedures a SELECT calls. Where the read key must be guaranteed harmless,
also connect with a database login that has no write permission.
"""

import re

from fastapi import HTTPException

# One left-to-right scan over the things that change how the rest of the
# text must be read. Order of discovery matters, not order of alternatives:
# a quote inside a comment, or a comment marker inside a string, is consumed
# by whichever construct opened first — exactly as the database does it.
_TOKEN_RE = re.compile(
    r"""
      (?P<string>'(?:[^']|'')*')        # 'text', with '' as an escaped quote
    | (?P<quoted>"(?:[^"]|"")*")        # "identifier"
    | (?P<comment>--|/\*|\#)            # start of a comment
    """,
    re.VERBOSE,
)

# Words that can make a statement that *starts* with SELECT/WITH modify
# data or structure: SELECT ... INTO, data-modifying CTEs, FOR UPDATE,
# procedure calls. Matched as whole words outside strings and quoted names,
# so a column like UPDATE_DATE or a value like 'DELETE' is unaffected.
_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|INTO|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE"
    r"|EXEC|EXECUTE|CALL)\b",
    re.IGNORECASE,
)

_STARTS_WITH_READ_RE = re.compile(r"\s*\(*\s*(SELECT|WITH)\b", re.IGNORECASE)


def _reject(reason: str) -> None:
    raise HTTPException(
        403,
        detail=f"The read API key may only run a single SELECT statement: {reason}. "
        "Use the write API key for anything else.",
    )


def ensure_read_only_sql(sql: str) -> None:
    """Raise HTTP 403 unless `sql` is a single statement that only reads."""
    if not _STARTS_WITH_READ_RE.match(sql):
        _reject("the statement must start with SELECT or WITH")

    def _blank(match: re.Match) -> str:
        if match.lastgroup == "comment":
            _reject("SQL comments are not allowed")
        # Keep a placeholder so removing a literal never joins two words.
        return "''"

    bare = _TOKEN_RE.sub(_blank, sql)

    if "'" in bare.replace("''", "") or '"' in bare:
        _reject("unbalanced quotes")
    if ";" in bare.strip().rstrip(";"):
        _reject("only one statement is allowed")
    forbidden = _FORBIDDEN_RE.search(bare)
    if forbidden:
        _reject(
            f"'{forbidden.group(1).upper()}' is not allowed "
            '(if it is a column name, wrap it in double quotes: "Name")'
        )
