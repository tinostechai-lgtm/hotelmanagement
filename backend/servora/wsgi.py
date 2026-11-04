"""WSGI entrypoint (used by Vercel's Django preset via WSGI_APPLICATION)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "servora.settings")

application = get_wsgi_application()
app = application


def _bootstrap():
    """On Vercel cold start: apply pending migrations and make sure SaaS plans
    exist, so no manual `manage.py` commands are needed after a deploy.

    * With DATABASE_URL (Postgres): guarded by an advisory lock so parallel cold
      starts don't migrate concurrently. Disable with SERVORA_AUTO_MIGRATE=0.
    * Without DATABASE_URL: throw-away SQLite demo in /tmp with sample data.
    """
    from django.core.management import call_command
    from django.db import connection

    if os.environ.get("DATABASE_URL"):
        if os.environ.get("SERVORA_AUTO_MIGRATE", "1") != "1":
            return
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        if not executor.migration_plan(executor.loader.graph.leaf_nodes()):
            return
        lock = connection.vendor == "postgresql"
        with connection.cursor() as c:
            if lock:
                c.execute("SELECT pg_advisory_lock(727274)")
            try:
                call_command("migrate", interactive=False, verbosity=1)
                call_command("seed", verbosity=1)  # plans only; never demo data
            finally:
                if lock:
                    c.execute("SELECT pg_advisory_unlock(727274)")
    elif os.environ.get("SERVORA_AUTO_DEMO", "1") == "1":
        call_command("migrate", interactive=False, verbosity=0)
        call_command("seed", demo=True, verbosity=0)


if os.environ.get("VERCEL"):
    try:
        _bootstrap()
    except Exception as exc:  # pragma: no cover - visible in Vercel logs and /healthz
        print("Servora bootstrap failed:", repr(exc))
