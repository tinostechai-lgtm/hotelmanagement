import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Device-local settings (server URL, printing options).
class AppConfig extends ChangeNotifier {
  AppConfig(this._prefs) {
    baseUrl = _prefs.getString(_kBaseUrl) ?? defaultBaseUrl;
    printFromDevice = _prefs.getBool(_kPrint) ?? false;
    btPrinterMac = _prefs.getString(_kBtMac) ?? '';
    btPrinterName = _prefs.getString(_kBtName) ?? '';
    fallbackLanPrinter = _prefs.getString(_kLan) ?? '';
    kdsSound = _prefs.getBool(_kSound) ?? true;
  }

  static const String defaultBaseUrl = 'https://servora.vercel.app';
  static const _kBaseUrl = 'cfg.base_url';
  static const _kPrint = 'cfg.print_from_device';
  static const _kBtMac = 'cfg.bt_mac';
  static const _kBtName = 'cfg.bt_name';
  static const _kLan = 'cfg.lan_printer';
  static const _kSound = 'cfg.kds_sound';

  final SharedPreferences _prefs;

  late String baseUrl;
  late bool printFromDevice;
  late String btPrinterMac;
  late String btPrinterName;

  /// "ip:port" used for jobs whose device has no network address.
  late String fallbackLanPrinter;
  late bool kdsSound;

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
