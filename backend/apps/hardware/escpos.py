"""Tiny ESC/POS renderer — works with Epson, TVS, Posiflex, Xprinter, Rugtek,
Everycom and other ESC/POS-compatible 58/80 mm thermal printers.

Text size:
  normal  – the printer's standard font (48 columns on 80 mm, 32 on 58 mm)
  large   – double-height letters, same columns (easier to read, same layout)
  xlarge  – double-height and double-width letters, half the columns
"""
import base64

ESC, GS = b"\x1b", b"\x1d"
INIT = ESC + b"@"
BOLD_ON, BOLD_OFF = ESC + b"E\x01", ESC + b"E\x00"
ALIGN_L, ALIGN_C, ALIGN_R = ESC + b"a\x00", ESC + b"a\x01", ESC + b"a\x02"
CUT = GS + b"V\x41\x03"
DRAWER_KICK = ESC + b"p\x00\x19\xfa"
BEEP = ESC + b"B\x03\x02"

SIZES = ("normal", "large", "xlarge")
_MODE = {"normal": 0x00, "large": 0x01, "xlarge": 0x11}  # GS ! n
BIG = 0x11


def cols(width_mm):
    return 32 if int(width_mm) <= 58 else 48


def clean_size(size):
    return size if size in SIZES else "normal"


def clean_width(width_mm):
    try:
        return 58 if int(width_mm) <= 58 else 80
    except (TypeError, ValueError):
        return 80


class Receipt:
    """Build a receipt as plain text, styled lines (for browser printing) and ESC/POS bytes at once."""

    def __init__(self, width_mm=80, size="normal", columns=None):
        self.size = clean_size(size)
        self.width_mm = clean_width(width_mm)
        full = int(columns) if columns else cols(self.width_mm)
        self.w = max(16, full // 2 if self.size == "xlarge" and not columns else full)
        self.base = _MODE[self.size]
        self.buf = bytearray(INIT) + GS + b"!" + bytes([self.base])
        self.lines = []
        self.styled = []

    def _enc(self, s):
        return s.replace("₹", "Rs.").encode("cp437", "replace")

    def text(self, s="", bold=False, big=False, align="left"):
        s = str(s)
        self.buf += {"left": ALIGN_L, "center": ALIGN_C, "right": ALIGN_R}[align]
        mode = BIG if big else self.base
        if bold:
            self.buf += BOLD_ON
        if mode != self.base:
            self.buf += GS + b"!" + bytes([mode])
        self.buf += self._enc(s) + b"\n"
        if mode != self.base:
            self.buf += GS + b"!" + bytes([self.base])
        if bold:
            self.buf += BOLD_OFF
        # Big text is twice as wide, unless the whole receipt is already double width.
        width = self.w // 2 if big and self.size != "xlarge" else self.w
        self.lines.append(s.center(width) if align == "center" else s.rjust(width) if align == "right" else s)
        self.styled.append({"t": s, "b": bool(bold), "big": bool(big), "a": align})
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
        qw, aw = (4, 8) if self.w < 32 else (5, 10)
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
