from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts import api as accounts
from apps.crm import api as crm
from apps.delivery import api as delivery
from apps.hardware import api as hardware
from apps.inventory import api as inventory
from apps.menu import api as menu
from apps.operations import api as ops
from apps.operations import public_api as public
from apps.subscriptions import api as subs
from apps.tenants import api as tenants



class OptionalSlashRouter(DefaultRouter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = "/?"


router = OptionalSlashRouter()
router.register("categories", menu.CategoryViewSet)
router.register("items", menu.ItemViewSet)
router.register("addon-groups", menu.AddonGroupViewSet)
router.register("hsn", menu.HSNViewSet)
router.register("stations", menu.StationViewSet)
router.register("areas", ops.AreaViewSet)
router.register("tables", ops.TableViewSet)
router.register("rooms", ops.RoomViewSet)
router.register("reservations", ops.ReservationViewSet)
router.register("orders", ops.OrderViewSet)
router.register("kots", ops.KOTViewSet)
router.register("notifications", ops.NotificationViewSet)
router.register("shifts", ops.ShiftViewSet)
router.register("customers", crm.CustomerViewSet)
router.register("coupons", crm.CouponViewSet)
router.register("feedback", crm.FeedbackViewSet)
router.register("delivery/zones", delivery.ZoneViewSet)
router.register("delivery/riders", delivery.RiderViewSet)
router.register("delivery/tasks", delivery.TaskViewSet)
router.register("delivery/settlements", delivery.SettlementViewSet)
router.register("inventory/suppliers", inventory.SupplierViewSet)
router.register("inventory/ingredients", inventory.IngredientViewSet)
router.register("inventory/movements", inventory.MovementViewSet)
router.register("inventory/recipes", inventory.RecipeViewSet)
router.register("inventory/purchase-orders", inventory.PurchaseOrderViewSet)
router.register("devices", hardware.DeviceViewSet)
router.register("print-jobs", hardware.PrintJobViewSet)
router.register("roles", accounts.RoleViewSet)
router.register("staff", accounts.StaffViewSet)

urlpatterns = [
    path("auth/login", accounts.login),
    path("auth/signup", accounts.signup),
    path("auth/refresh", TokenRefreshView.as_view()),
    path("auth/pin", accounts.pin_switch),
    path("me", accounts.me),
    path("restaurant", tenants.restaurant),
    path("bootstrap", tenants.pos_bootstrap),
    path("reports/summary", tenants.reports),
    path("reports/insights", tenants.insights),
    path("plans", subs.plans),
    path("subscription", subs.current),
    path("subscription/checkout", subs.checkout),
    path("subscription/verify", subs.verify),
    path("razorpay/webhook", subs.webhook),
    path("rider", delivery.RiderAppView.as_view()),
    path("delivery/live-map", delivery.live_map),
    path("hardware/agent", hardware.agent_poll),
    path("hardware/scale", hardware.scale_reading),
    path("public/<slug:slug>/store", public.store),
    path("public/<slug:slug>/quote", public.delivery_quote),
    path("public/<slug:slug>/order", public.place_order),
    path("public/<slug:slug>/verify-payment", public.verify_payment),
    path("public/<slug:slug>/call-waiter", public.call_waiter),
    path("public/track/<str:token>", public.track),
    path("public/track/<str:token>/feedback", public.feedback),
    path("integrations/<slug:slug>/<str:source>/order", public.aggregator_webhook),
    path("", include(router.urls)),
]
