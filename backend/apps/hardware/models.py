import secrets

from django.db import models
from django.utils import timezone

from apps.tenants.models import TenantModel


class Device(TenantModel):
    class Kind(models.TextChoices):
        RECEIPT_PRINTER = "receipt_printer", "Receipt / bill printer"
        KOT_PRINTER = "kot_printer", "KOT / kitchen printer"
        LABEL_PRINTER = "label_printer", "Label / sticker printer"
        KDS = "kds", "Kitchen display screen"
        CASH_DRAWER = "cash_drawer", "Cash drawer"
        CUSTOMER_DISPLAY = "customer_display", "Customer-facing display"
        WEIGHING_SCALE = "weighing_scale", "Weighing scale"
        BARCODE_SCANNER = "barcode_scanner", "Barcode / QR scanner"
        CARD_TERMINAL = "card_terminal", "Card / UPI POS terminal"
        TOKEN_DISPLAY = "token_display", "Order-ready token display"
        POS_TERMINAL = "pos_terminal", "POS terminal / tablet"

    class Connection(models.TextChoices):
        NETWORK = "network", "LAN / Wi-Fi (IP)"
        USB = "usb", "USB"
        BLUETOOTH = "bluetooth", "Bluetooth"
        SERIAL = "serial", "Serial / COM"
        BROWSER = "browser", "Browser (WebUSB / WebSerial)"
        CLOUD = "cloud", "Cloud / SDK"
        HID = "hid", "Keyboard (HID)"

    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    connection = models.CharField(max_length=10, choices=Connection.choices, default=Connection.NETWORK)
    address = models.CharField(max_length=120, blank=True, help_text="IP:port, USB vendor:product, BT MAC, or COM port")
    paper_width = models.PositiveSmallIntegerField(default=80, help_text="58 or 80 mm")
    copies = models.PositiveSmallIntegerField(default=1)
    stations = models.ManyToManyField("menu.KitchenStation", blank=True, help_text="KOT routing for kitchen printers / KDS")
    is_default = models.BooleanField(default=False)
    opens_drawer = models.BooleanField(default=False, help_text="Kick cash drawer when a cash bill is printed")
    vendor = models.CharField(max_length=40, blank=True, help_text="Epson, TVS, Posiflex, Pine Labs, Razorpay POS …")
    config = models.JSONField(default=dict, blank=True)
    agent_key = models.CharField(max_length=48, unique=True, editable=False)
    last_seen = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["kind", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.agent_key:
            self.agent_key = "dev_" + secrets.token_urlsafe(30)
        super().save(*args, **kwargs)

    @property
    def is_online(self):
        return bool(self.last_seen and (timezone.now() - self.last_seen).total_seconds() < 90)


class PrintJob(TenantModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent to agent"
        DONE = "done", "Printed"
        FAILED = "failed", "Failed"

    device = models.ForeignKey(Device, null=True, blank=True, on_delete=models.CASCADE, related_name="jobs")
    kind = models.CharField(max_length=12)  # kot / bill / test / drawer / label / display
    title = models.CharField(max_length=80, blank=True)
    text = models.TextField(help_text="Plain-text rendering (for preview & fallback)")
    escpos_b64 = models.TextField(blank=True, help_text="Raw ESC/POS bytes, base64")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["created_at"]
