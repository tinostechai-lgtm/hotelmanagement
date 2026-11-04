# Servora Hardware Agent

A small program that lets **Servora** (which runs in the cloud) print bills and
KOTs, open the cash drawer, show totals on the customer display and read the
weighing scale — using the hardware sitting in your restaurant.

Run it on any computer that stays on at the counter: a Windows PC, a Raspberry
Pi, or a mini-PC. One agent handles **all** the printers and devices in the
restaurant.

---

## Set it up in 3 steps

### 1. Download
Download this `hardware-agent` folder (or the ZIP from Servora → Settings →
Hardware) and put it somewhere permanent, e.g. `C:\Servora` or your home folder.

### 2. Copy your device key
In the Servora dashboard open **Settings → Hardware**, add (or open) the device
for this counter computer, and copy its **Device key** (it starts with `dev_`).
Keep it private — it works like a password for your printers.

While you are there, add each printer / drawer / display / scale with its
**connection** and **address** (see the table under "What to type as the
address").

### 3. Run the installer
- **Windows:** double-click `install_windows.bat`. If Python is missing it opens
  the download page — install it, tick **"Add python.exe to PATH"**, then
  double-click the installer again. Paste your device key when asked.
- **Raspberry Pi / Linux:** open a terminal in this folder and run
  `sudo ./install_linux.sh`, then paste your device key when asked.

That's it. The agent starts automatically every time the computer starts.
Press **Print test page** next to a printer in Servora to check everything works.

---

## What to type as the address

| Your printer is connected by… | Connection in Servora | Address example |
|---|---|---|
| Network cable / Wi-Fi (has an IP) | LAN / Wi-Fi | `192.168.1.50` or `192.168.1.50:9100` |
| USB cable | USB | `04b8:0202` (shown by `discover`) — or on Windows simply `win:EPSON TM-T82 Receipt` |
| Serial / COM port, or USB-to-serial | Serial / COM | `COM3`, `COM3@19200`, `/dev/ttyUSB0@9600` |
| Bluetooth | Bluetooth | Windows: the COM port Windows assigned after pairing, e.g. `COM5`. Linux/Pi: the MAC, e.g. `66:22:B3:01:2C:9A` |
| Any printer already installed in Windows | USB (or any) | `win:<exact printer name>` |
| Any printer already installed in CUPS (Linux/Mac) | USB (or any) | `cups:<printer name>` |

Not sure? Run the finder — it lists network printers on your Wi-Fi, USB
printers and COM ports:

```
python servora_agent.py discover
```

Test any printer directly, without Servora:

```
python servora_agent.py test --address 192.168.1.50
python servora_agent.py test --address COM3 --drawer      # also opens the cash drawer
python servora_agent.py test --address COM4 --display --text "Welcome!"
```

---

## Supported hardware

| Device | Works with | How it connects |
|---|---|---|
| Receipt / KOT printers | **Epson TM series** (TM-T82, TM-T88, TM-m30…), **TVS RP series** (RP 3160, RP 3200…), **Posiflex**, **Xprinter**, **Rugtek**, **Everycom**, **Citizen**, **Star** (set to ESC/POS emulation mode) and any ESC/POS 58/80 mm thermal printer | LAN, Wi-Fi, USB, Serial, Bluetooth |
| Label / sticker printers | Models with ESC/POS mode print directly. TSPL-only label printers (TSC, many Xprinter label models) need TSPL output — use a `win:`/`cups:` address with the vendor driver, or ask Servora support | LAN, USB |
| Cash drawer | Any drawer plugged into the printer's **RJ11 "DK" port** — the printer kicks it open after cash bills | Through the printer |
| Customer pole display | 2 × 20 VFD / LCD pole displays (Posiflex PD, Epson DM-D, generic ESC/POS) | Serial / USB-serial |
| Weighing scale | **Essae**, **Avery**, **Atom** and most retail scales with continuous output | RS-232 or USB-serial |
| Barcode / QR scanner | Any scanner in keyboard (HID) mode | **No agent needed** — it types straight into Servora |
| Card / UPI terminals | **Pine Labs**, **Razorpay POS**, **Paytm EDC** | Handled by Servora's cloud / app integration with the provider's SDK — **not** by this agent |
| Kitchen display (KDS), token display | Any tablet / TV with a browser | Open the Servora KDS page — no agent needed |

**Weighing scale tips:** set the scale to *continuous* (or "stream") output.
Typical baud rates: Essae 9600, Avery 9600, Atom 2400 — e.g. address
`COM3@9600`. If your scale only answers when asked, add
`"poll_command": "W\r\n"` to the device's config in Servora.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Device key rejected" in the log | Copy the key again from Settings → Hardware and run `python servora_agent.py setup` |
| Network printer "unreachable" | Make sure the printer and this computer are on the same Wi-Fi/LAN. Print the printer's self-test (hold FEED while switching on) to see its IP. Give it a fixed IP in your router. |
| USB printer "Access denied" (Linux) | The Linux installer runs the agent as root, which fixes this. On Windows, prefer `win:<printer name>`. |
| USB printer not found on Windows with `04b8:0202` style address | Windows printer drivers lock the port — use `win:<printer name>` instead (needs `pywin32`, installed by the installer). |
| "requires the optional package" | Run `python -m pip install -r requirements-optional.txt` |
| Internet goes down | Nothing to do — the agent keeps retrying and catches up automatically when the internet returns. |

Logs: `servora-agent.log` next to `servora_agent.py` (Windows) or
`journalctl -u servora-agent -f` (Linux).

---

## For technical staff

- Single file, Python 3.9+, standard library only. Optional: `pyusb`,
  `pyserial`, `pywin32` (see `requirements-optional.txt`).
- Protocol: `GET /api/hardware/agent` with header `X-Device-Key` returns
  `{restaurant, devices, jobs}` (jobs are marked *sent* when read);
  `POST /api/hardware/agent` with `{results:[{id, ok, error}], scale_weight?, online_devices?}`.
- Jobs contain ready-made ESC/POS bytes (base64) including cut and drawer
  kick; the agent delivers them unchanged. `display` jobs / customer display
  devices get the job text as a 2×20 screen.
- Polls every 2 s (`poll_interval`), 3 delivery attempts with exponential
  backoff, health-checks printers every 60 s, exponential backoff up to 60 s
  during outages, results that could not be reported are re-sent next cycle.
- `config.json` keys: `server_url`, `device_key`, `poll_interval`, and optional
  `health_interval`, `retries`, `retry_backoff`, `socket_timeout`,
  `http_timeout`, `default_baud`, `log_file`, `log_level`. Environment
  overrides: `SERVORA_SERVER_URL`, `SERVORA_DEVICE_KEY`, `SERVORA_AGENT_CONFIG`.
- Manual run: `python servora_agent.py run` (Ctrl+C to stop).
- Tests: `python -m unittest discover -s hardware-agent/tests` (from repo root).
