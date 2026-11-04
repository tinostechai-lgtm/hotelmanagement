"""Tiny ESC/POS renderer — works with Epson, TVS, Posiflex, Xprinter, Rugtek,
Everycom and other ESC/POS-compatible 58/80 mm thermal printers."""
import base64

ESC, GS = b"\x1b", b"\x1d"
INIT = ESC + b"@"
BOLD_ON, BOLD_OFF = ESC + b"E\x01", ESC + b"E\x00"
DOUBLE_ON, DOUBLE_OFF = GS + b"!\x11", GS + b"!\x00"
ALIGN_L, ALIGN_C, ALIGN_R = ESC + b"a\x00", ESC + b"a\x01", ESC + b"a\x02"
CUT = GS + b"V\x41\x03"
DRAWER_KICK = ESC + b"p\x00\x19\xfa"
BEEP = ESC + b"B\x03\x02"


def cols(width_mm):
    return 32 if int(width_mm) <= 58 else 48


class Receipt:
    """Build a receipt as both plain text and ESC/POS bytes simultaneously."""

    def __init__(self, width_mm=80):
        self.w = cols(width_mm)
        self.buf = bytearray(INIT)
        self.lines = []

    def _enc(self, s):
        return s.replace("₹", "Rs.").encode("cp437", "replace")

    def text(self, s="", bold=False, big=False, align="left"):
        self.buf += {"left": ALIGN_L, "center": ALIGN_C, "right": ALIGN_R}[align]
        if bold:
            self.buf += BOLD_ON
        if big:
            self.buf += DOUBLE_ON
        self.buf += self._enc(s) + b"\n"
        if big:
            self.buf += DOUBLE_OFF
        if bold:
            self.buf += BOLD_OFF
        width = self.w // 2 if big else self.w
        self.lines.append(s.center(width) if align == "center" else s.rjust(width) if align == "right" else s)
        return self

    def rule(self, ch="-"):
        return self.text(ch * self.w)

    def pair(self, left, right, bold=False):
        left, right = str(left), str(right)
        space = max(1, self.w - len(left) - len(right))
        if len(left) + len(right) + 1 > self.w:
            self.text(left[: self.w], bold=bold)
            return self.text(right.rjust(self.w), bold=bold)
        return self.text(left + " " * space + right, bold=bold)

    def row(self, name, qty, amount):
        qw, aw = 5, 10
        nw = self.w - qw - aw
        name = str(name)
        first = True
        while name or first:
            chunk, name = name[:nw], name[nw:]
            if first:
                self.text(chunk.ljust(nw) + str(qty).rjust(qw) + str(amount).rjust(aw))
                first = False
            else:
                self.text("  " + chunk)
        return self

    def feed(self, n=1):
        for _ in range(n):
            self.text("")
        return self

    def cut(self, drawer=False, beep=False):
        self.feed(3)
        if beep:
            self.buf += BEEP
        self.buf += CUT
        if drawer:
            self.buf += DRAWER_KICK
        return self

    @property
    def plain(self):
        return "\n".join(self.lines)

    @property
    def b64(self):
        return base64.b64encode(bytes(self.buf)).decode()
