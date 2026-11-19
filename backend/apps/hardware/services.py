from decimal import Decimal

from django.utils import timezone

from .escpos import DRAWER_KICK, Receipt
from .models import Device, PrintJob


def _fmt(v):
    return f"{Decimal(v):.2f}"


def render_kot(kot, width=80, size="normal", columns=None):
    o = kot.order
    r = Receipt(width, size, columns)
    r.text("KOT", bold=True, big=True, align="center")
    if kot.station:
        r.text(kot.station.name.upper(), bold=True, align="center")
    r.pair(f"KOT #{kot.number}", timezone.localtime(kot.created_at).strftime("%d-%m %H:%M"))
    r.pair(f"Order {o.number}", o.label, bold=True)
    if o.taken_by:
        r.text(f"By: {o.taken_by}")
    r.rule()
    for li in kot.lines.all():
        qty = f"{li.quantity.normalize():f}"
        r.text(f"{qty} x {li.display_name}", bold=True)
        for a in li.addons:
            r.text(f"   + {a.get('name')}")
        if li.notes:
            r.text(f"   * {li.notes}")
    if o.notes:
        r.rule()
        r.text(f"NOTE: {o.notes}", bold=True)
    return r.cut(beep=True)


def render_bill(bill, width=80, size="normal", columns=None):
    o = bill.order
    rest = bill.restaurant
    r = Receipt(width, size, columns)
    r.text(rest.name, bold=True, big=True, align="center")
    for line in filter(None, [rest.address, rest.phone and f"Ph: {rest.phone}", rest.gst_enabled and rest.gstin and f"GSTIN: {rest.gstin}",
                              rest.fssai and f"FSSAI: {rest.fssai}"]):
        r.text(line, align="center")
    r.rule("=")
    r.text("TAX INVOICE" if rest.gst_enabled else "BILL", bold=True, align="center")
    r.pair(f"Bill: {bill.number}", timezone.localtime(bill.created_at).strftime("%d-%m-%Y %H:%M"))
    r.pair(o.label, f"Order {o.number}")
    if o.customer_name or o.customer_phone:
        r.text(f"Guest: {o.customer_name} {o.customer_phone}".strip())
    if bill.label:
        r.text(bill.label)
    r.rule()
    r.row("Item", "Qty", "Amount")
    r.rule()
    for line in bill.lines:
        r.row(line["name"], line["qty"], _fmt(line["amount"]))
    r.rule()
    r.pair("Subtotal", _fmt(bill.subtotal))
    if bill.discount:
        r.pair("Discount", "-" + _fmt(bill.discount))
    if bill.service_charge:
        r.pair("Service charge", _fmt(bill.service_charge))
    if bill.tax and rest.gst_enabled:
        half = Decimal(bill.tax) / 2
        r.pair("CGST", _fmt(half))
        r.pair("SGST", _fmt(Decimal(bill.tax) - half))
    if bill.extra_charges:
        r.pair("Delivery/Packing", _fmt(bill.extra_charges))
    if bill.round_off:
        r.pair("Round off", _fmt(bill.round_off))
    r.rule("=")
    r.pair("GRAND TOTAL", f"Rs.{_fmt(bill.total)}", bold=True)
    r.rule("=")
    for p in bill.payments.filter(status="success"):
        r.pair(p.get_method_display(), _fmt(p.amount))
    if rest.bill_footer:
        r.feed()
        r.text(rest.bill_footer, align="center")
    r.text("Powered by Servora", align="center")
    cash = bill.payments.filter(method="cash", status="success").exists()
    return r.cut(drawer=cash)


def device_size(device):
    """Text size chosen for this printer (normal / large / xlarge)."""
    return ((device.config or {}).get("text_size") if device else None) or "normal"


def _queue(restaurant, device, kind, title, receipt, order=None, source=""):
    copies = device.copies if device else 1
    jobs = []
    for _ in range(max(1, copies)):
        jobs.append(PrintJob.objects.create(restaurant=restaurant, device=device, kind=kind, title=title,
                                            text=receipt.plain, escpos_b64=receipt.b64, order=order, source=source))
    return jobs


def render_source(job, width=None, size=None, columns=None):
    """Re-render a job's KOT / bill for the printer that will actually print it (paper width, text size).
    Returns a Receipt, or None when the job has nothing to re-render (test page, drawer kick)."""
    from apps.operations.models import KOT, Bill

    kind, _, pk = (job.source or "").partition(":")
    width = width or (job.device.paper_width if job.device else 80)
    size = size or device_size(job.device)
    if kind == "kot":
        kot = KOT.objects.filter(restaurant=job.restaurant, pk=pk).select_related("order", "station").first()
        return render_kot(kot, width, size, columns) if kot else None
    if kind == "bill":
        bill = Bill.objects.filter(restaurant=job.restaurant, pk=pk).select_related("order", "restaurant").first()
        return render_bill(bill, width, size, columns) if bill else None
    return None


def print_kot(kot):
    devices = Device.objects.filter(restaurant=kot.restaurant, is_active=True, kind=Device.Kind.KOT_PRINTER)
    targets = [d for d in devices if not d.stations.exists() or (kot.station_id and d.stations.filter(pk=kot.station_id).exists())]
    if not targets:
        targets = list(Device.objects.filter(restaurant=kot.restaurant, is_active=True, kind=Device.Kind.RECEIPT_PRINTER, is_default=True)[:1])
    jobs = []
    for d in targets or [None]:
        jobs += _queue(kot.restaurant, d, "kot", f"KOT {kot.number}", render_kot(kot, d.paper_width if d else 80, device_size(d)),
                       order=kot.order, source=f"kot:{kot.pk}")
    kot.printed = True
    kot.save(update_fields=["printed"])
    return jobs


def print_bill(bill, device=None):
    d = device or Device.objects.filter(restaurant=bill.restaurant, is_active=True, kind=Device.Kind.RECEIPT_PRINTER).order_by("-is_default").first()
    return _queue(bill.restaurant, d, "bill", f"Bill {bill.number}", render_bill(bill, d.paper_width if d else 80, device_size(d)),
                  order=bill.order, source=f"bill:{bill.pk}")


def print_test(device):
    r = Receipt(device.paper_width, device_size(device))
    r.text("SERVORA", bold=True, big=True, align="center")
    r.text("Printer test successful", align="center")
    r.pair("Device", device.name)
    r.pair("Connection", device.get_connection_display())
    r.pair("Paper", f"{device.paper_width} mm")
    r.cut(drawer=device.opens_drawer)
    return _queue(device.restaurant, device, "test", "Test print", r)


def open_drawer(restaurant):
    import base64

    d = Device.objects.filter(restaurant=restaurant, is_active=True, kind__in=[Device.Kind.CASH_DRAWER, Device.Kind.RECEIPT_PRINTER]).order_by("kind").first()
    return PrintJob.objects.create(restaurant=restaurant, device=d, kind="drawer", title="Open drawer", text="[open cash drawer]",
                                   escpos_b64=base64.b64encode(DRAWER_KICK).decode())
