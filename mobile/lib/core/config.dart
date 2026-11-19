import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'json.dart';

/// Device-local settings (server URL, printing options).
class AppConfig extends ChangeNotifier {
  AppConfig(this._prefs) {
    baseUrl = _prefs.getString(_kBaseUrl) ?? defaultBaseUrl;
    printFromDevice = _prefs.getBool(_kPrint) ?? false;
    btPrinterMac = _prefs.getString(_kBtMac) ?? '';
    btPrinterName = _prefs.getString(_kBtName) ?? '';
    fallbackLanPrinter = _prefs.getString(_kLan) ?? '';
    kotBtMac = _prefs.getString(_kKotBtMac) ?? '';
    kotBtName = _prefs.getString(_kKotBtName) ?? '';
    kotLan = _prefs.getString(_kKotLan) ?? '';
    autoPrint = _prefs.getBool(_kAuto) ?? true;
    printKotHere = _prefs.getBool(_kKotHere) ?? true;
    printBillHere = _prefs.getBool(_kBillHere) ?? true;
    paperWidth = _prefs.getInt(_kPaper) ?? 80;
    textSize = _prefs.getString(_kSize) ?? 'large';
    kdsSound = _prefs.getBool(_kSound) ?? true;
    deviceId = _prefs.getString(_kDevice) ?? '';
    if (deviceId.isEmpty) {
      deviceId = 'app-${uuid4()}';
      _prefs.setString(_kDevice, deviceId);
    }
  }

  /// Stable id of this phone (sent as X-Device-Id): table holds and crew logins are per phone.
  late String deviceId;
  static const _kDevice = 'cfg.device_id';

  static const String defaultBaseUrl = 'https://web-rust-six-43.vercel.app';

  /// One-tap demo logins on the sign-in screen (the live test restaurant).
  /// Set to false for a production build without demo accounts.
  static const bool showDemoLogins = true;
  static const String demoPassword = 'Live@Check2026';
  static const List<List<String>> demoUsers = [
    ['Owner', '9000000501'],
    ['Manager', '9000000506'],
    ['Captain', '9000000502'],
    ['Cashier', '9000000503'],
    ['Kitchen', '9000000504'],
    ['Rider', '9000000505'],
    ['Store', '9000000507'],
  ];
  static const _kBaseUrl = 'cfg.base_url';
  static const _kPrint = 'cfg.print_from_device';
  static const _kBtMac = 'cfg.bt_mac';
  static const _kBtName = 'cfg.bt_name';
  static const _kLan = 'cfg.lan_printer';
  static const _kSound = 'cfg.kds_sound';
  static const _kKotBtMac = 'cfg.kot_bt_mac';
  static const _kKotBtName = 'cfg.kot_bt_name';
  static const _kKotLan = 'cfg.kot_lan';
  static const _kAuto = 'cfg.auto_print';
  static const _kKotHere = 'cfg.print_kot_here';
  static const _kBillHere = 'cfg.print_bill_here';
  static const _kPaper = 'cfg.paper_width';
  static const _kSize = 'cfg.text_size';

  final SharedPreferences _prefs;

  late String baseUrl;
  late bool printFromDevice;
  late String btPrinterMac;
  late String btPrinterName;

  /// "ip:port" used for jobs whose device has no network address.
  late String fallbackLanPrinter;
  late bool kdsSound;

  /// Separate kitchen (KOT) printer; empty = KOTs go to the main printer above.
  late String kotBtMac;
  late String kotBtName;
  late String kotLan;

  /// Print straight away when this phone sends a KOT / makes a bill.
  late bool autoPrint;
  late bool printKotHere;
  late bool printBillHere;

  /// 58 or 80 (mm) and normal / large / xlarge letters.
  late int paperWidth;
  late String textSize;

  bool get hasMainPrinter => btPrinterMac.isNotEmpty || fallbackLanPrinter.isNotEmpty;
  bool get hasKotPrinter => kotBtMac.isNotEmpty || kotLan.isNotEmpty;

  /// Printer for a job kind: 'bt:<mac>' or 'lan:<ip:port>', or null when this phone has none.
  String? targetFor(String kind) {
    if (kind == 'kot' && hasKotPrinter) return kotBtMac.isNotEmpty ? 'bt:$kotBtMac' : 'lan:$kotLan';
    if (btPrinterMac.isNotEmpty) return 'bt:$btPrinterMac';
    if (fallbackLanPrinter.isNotEmpty) return 'lan:$fallbackLanPrinter';
    return null;
  }

  Future<void> setKotPrinter({String mac = '', String name = '', String lan = ''}) async {
    kotBtMac = mac;
    kotBtName = name;
    kotLan = lan.trim();
    await _prefs.setString(_kKotBtMac, kotBtMac);
    await _prefs.setString(_kKotBtName, kotBtName);
    await _prefs.setString(_kKotLan, kotLan);
    notifyListeners();
  }

  Future<void> setPrintOptions({bool? auto, bool? kot, bool? bill, int? paper, String? size}) async {
    if (auto != null) await _prefs.setBool(_kAuto, autoPrint = auto);
    if (kot != null) await _prefs.setBool(_kKotHere, printKotHere = kot);
    if (bill != null) await _prefs.setBool(_kBillHere, printBillHere = bill);
    if (paper != null) await _prefs.setInt(_kPaper, paperWidth = paper);
    if (size != null) await _prefs.setString(_kSize, textSize = size);
    notifyListeners();
  }

  Future<void> setBaseUrl(String value) async {
    var v = value.trim();
    if (v.isEmpty) v = defaultBaseUrl;
    if (!v.startsWith('http://') && !v.startsWith('https://')) v = 'https://$v';
    while (v.endsWith('/')) {
      v = v.substring(0, v.length - 1);
    }
    if (v.endsWith('/api')) v = v.substring(0, v.length - 4);
    baseUrl = v;
    await _prefs.setString(_kBaseUrl, v);
    notifyListeners();
  }

  Future<void> setPrintFromDevice(bool v) async {
    printFromDevice = v;
    await _prefs.setBool(_kPrint, v);
    notifyListeners();
  }

  Future<void> setBluetoothPrinter(String mac, String name) async {
    btPrinterMac = mac;
    btPrinterName = name;
    await _prefs.setString(_kBtMac, mac);
    await _prefs.setString(_kBtName, name);
    notifyListeners();
  }

  Future<void> setFallbackLanPrinter(String v) async {
    fallbackLanPrinter = v.trim();
    await _prefs.setString(_kLan, fallbackLanPrinter);
    notifyListeners();
  }

  Future<void> setKdsSound(bool v) async {
    kdsSound = v;
    await _prefs.setBool(_kSound, v);
    notifyListeners();
  }
}
