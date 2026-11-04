"""WSGI entrypoint (used by Vercel's Django preset via WSGI_APPLICATION)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "servora.settings")

application = get_wsgi_application()
app = application

# Demo mode on Vercel without an external database: build a throw-away SQLite
# DB in /tmp on cold start so the site works right after the first deploy.
# Set DATABASE_URL (Postgres) for real use, or SERVORA_AUTO_DEMO=0 to disable.
if os.environ.get("VERCEL") and not os.environ.get("DATABASE_URL") and os.environ.get("SERVORA_AUTO_DEMO", "1") == "1":
    from django.core.management import call_command

    try:
        call_command("migrate", interactive=False, verbosity=0)
        call_command("seed", demo=True, verbosity=0)
    except Exception as exc:  # pragma: no cover - visible in Vercel logs
        print("Servora demo bootstrap failed:", exc)
