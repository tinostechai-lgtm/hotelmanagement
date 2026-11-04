def tenant(request):
    from django.conf import settings

    from apps.superadmin.models import get_settings

    r = getattr(request, "restaurant", None)
    m = getattr(request, "membership", None)
    return {"demo_mode": settings.DEMO_MODE, "show_demo_login": settings.DEMO_MODE or settings.DEBUG, "platform": get_settings(),
            "restaurant": r, "membership": m, "subscription": r.subscription if r else None}
