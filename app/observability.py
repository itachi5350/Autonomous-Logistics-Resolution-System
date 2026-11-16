"""Records one row per model call. Metadata only: no prompts and no customer data are stored."""
import psycopg

from app.config import DATABASE_URL


def log_call(case_id: str | None, agent: str, step: str, model: str, ok: bool,
             retries: int, latency_ms: int, error: str | None = None) -> None:
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute(
                "INSERT INTO agent_calls (case_id, agent, step, model, ok, retries, latency_ms, error) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (case_id, agent, step, model, ok, retries, latency_ms, error),
            )
    except Exception as err:      # logging must never break a case
        print(f"[observability] could not record a model call: {err!r}")