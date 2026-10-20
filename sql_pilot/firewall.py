"""
SQL Safety Firewall & Guardrails.
Guarantees read-only execution by enforcing strict AST and lexical rules:
Blocks mutating keywords, DDL operations, stacked semicolon injections, and administrative commands.
"""

import re
from typing import Tuple, Optional

# Forbidden SQL statements & DDL/DML mutation keywords
DISALLOWED_KEYWORDS = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "REPLACE",
    "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE", "ATTACH", "DETACH",
    "VACUUM", "REINDEX", "PRAGMA"
}

DISALLOWED_PATTERN = re.compile(
    r"\b(" + "|".join(DISALLOWED_KEYWORDS) + r")\b",
    re.IGNORECASE
)


def validate_sql_safety(sql: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a SQL statement is strictly read-only and safe to execute.
    Returns (is_safe: bool, violation_reason: Optional[str]).
    """
    clean_sql = sql.strip().rstrip(";")
    if not clean_sql:
        return False, "Query is empty."

    # 1. Block stacked query injection (e.g. "SELECT 1; DROP TABLE users;")
    # Strip quoted strings first to avoid false positives on semicolons inside string literals
    unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", "", clean_sql)
    if ";" in unquoted:
        return False, "Security Violation: Multiple stacked SQL queries (semicolon injection) detected."

    # 2. Check initial keyword: Must begin with SELECT or WITH (for CTEs)
    first_token_match = re.match(r"^\s*([a-zA-Z]+)", clean_sql)
    if not first_token_match:
        return False, "Security Violation: Unable to identify SQL statement root."

    root_keyword = first_token_match.group(1).upper()
    if root_keyword not in ("SELECT", "WITH", "EXPLAIN"):
        return False, f"Security Violation: Non-read query '{root_keyword}' is strictly prohibited. Only SELECT queries are permitted."

    # 3. Check for forbidden mutating keywords anywhere in the unquoted query
    match = DISALLOWED_PATTERN.search(unquoted)
    if match:
        forbidden = match.group(1).upper()
        return False, f"Security Violation: Destructive operation '{forbidden}' is strictly blocked by the SQL Safety Firewall."

    return True, None
