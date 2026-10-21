import re

MAX_ROWS = 50

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|execute|"
    r"vacuum|analyze|set|reset|listen|notify|lock|pg_sleep|pg_read_file|lo_import|lo_export)\b",
    re.IGNORECASE,
)


class UnsafeSQL(ValueError):
    pass


def make_safe(sql: str) -> str:
    """Return a version of `sql` that is safe to run, or raise UnsafeSQL."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeSQL("empty query")
    if ";" in cleaned:
        raise UnsafeSQL("only one statement is allowed")
    if "--" in cleaned or "/*" in cleaned:
        raise UnsafeSQL("comments are not allowed")
    if not re.match(r"(select|with)\b", cleaned, re.IGNORECASE):
        raise UnsafeSQL("query must start with SELECT or WITH")
    bad = FORBIDDEN.search(cleaned)
    if bad:
        raise UnsafeSQL(f"forbidden keyword: {bad.group(0)}")
    return f"SELECT * FROM ({cleaned}) AS q LIMIT {MAX_ROWS}"