from .models import Restaurant


class TenantMiddleware:
    """Resolve the active restaurant for the request.

    Order of precedence: ``X-Restaurant`` header (API / apps), the session
    (web dashboard), then the user's first membership.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.restaurant = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            request.restaurant = resolve_restaurant(request, user)
        return self.get_response(request)


def resolve_restaurant(request, user):
    from apps.accounts.models import Membership

    memberships = Membership.objects.filter(user=user, is_active=True).select_related("restaurant")
    wanted = request.headers.get("X-Restaurant") or request.session.get("restaurant_id")
    if wanted:
        m = memberships.filter(restaurant_id=wanted).first() if str(wanted).isdigit() else memberships.filter(restaurant__slug=wanted).first()
        if m:
            request.membership = m
            return m.restaurant
    m = memberships.first()
    request.membership = m
    return m.restaurant if m else None
