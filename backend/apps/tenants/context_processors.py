def tenant(request):
    r = getattr(request, "restaurant", None)
    m = getattr(request, "membership", None)
    from django.conf import settings

    return {"demo_mode": settings.DEMO_MODE, "restaurant": r, "membership": m, "subscription": r.subscription if r else None}
