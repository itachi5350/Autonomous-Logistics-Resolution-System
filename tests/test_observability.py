from app import observability


def test_logging_never_breaks_the_caller(monkeypatch):
    def database_down(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(observability.psycopg, "connect", database_down)
    observability.log_call("case-1", "db_agent", "write_sql", "some-model", True, 0, 12)  # must not raise