"""Vercel entrypoint: exposes the Django WSGI app as ``app``."""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "servora.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()

# Demo mode without an external database: build a throw-away SQLite DB in /tmp
# on cold start so the site works immediately after the first deploy.
if not os.environ.get("DATABASE_URL") and os.environ.get("SERVORA_AUTO_DEMO", "1") == "1":
    from django.core.management import call_command

    try:
        call_command("migrate", interactive=False, verbosity=0)
        call_command("seed", demo=True, verbosity=0)
    except Exception as exc:  # pragma: no cover - logged to Vercel
        print("Demo bootstrap failed:", exc)
