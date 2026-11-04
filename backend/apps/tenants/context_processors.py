def tenant(request):
    r = getattr(request, "restaurant", None)
    m = getattr(request, "membership", None)
    return {"restaurant": r, "membership": m, "subscription": r.subscription if r else None}
