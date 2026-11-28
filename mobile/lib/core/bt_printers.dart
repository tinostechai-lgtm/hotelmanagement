import 'dart:async';
import 'dart:io';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:permission_handler/permission_handler.dart';

/// A printer found by a Bluetooth search.
class FoundPrinter {
  const FoundPrinter(this.id, this.name, this.rssi);
  final String id;
  final String name;
  final int rssi;
}

/// Bluetooth helpers for thermal printers:
/// * asks Android for the "Nearby devices" (and location) permission - without it Android
///   silently blocks every printer;
/// * prints over Bluetooth Low Energy (BLE), used by many small 58 mm "mobile printers"
///   (Posiflow PSF-588 / SC588, Goojprt, MTP-II, Xprinter mini ...) that don't work over classic Bluetooth.
class BtPrinters {
  BtPrinters._();

  /// Asks for the Bluetooth permissions. Returns true when printing over Bluetooth is allowed.
  static Future<bool> ensurePermissions() async {
    if (!Platform.isAndroid) return true;
    try {
      final st = await [Permission.bluetoothConnect, Permission.bluetoothScan, Permission.locationWhenInUse].request();
      final connect = st[Permission.bluetoothConnect];
      // Android 11 and older report "granted" for the new Bluetooth permissions.
      return connect == null || connect.isGranted || connect.isLimited;
    } catch (_) {
      return true; // let the plugin try; it reports its own error
    }
  }

  /// True when the user said "Don't allow" for good - only phone Settings can fix it.
  static Future<bool> blockedForGood() async {
    if (!Platform.isAndroid) return false;
    try {
      return await Permission.bluetoothConnect.isPermanentlyDenied;
    } catch (_) {
      return false;
    }
  }

  static Future<bool> openSettings() => openAppSettings();

  /// Searches for nearby Bluetooth (BLE) printers for [seconds].
  static Future<List<FoundPrinter>> scan({int seconds = 6}) async {
    if (!await ensurePermissions()) throw Exception('Allow "Nearby devices" for Servora first');
    if (await FlutterBluePlus.isSupported == false) throw Exception('This phone has no Bluetooth');
    if (FlutterBluePlus.adapterStateNow != BluetoothAdapterState.on && Platform.isAndroid) {
      try {
        await FlutterBluePlus.turnOn();
      } catch (_) {
        throw Exception('Turn on Bluetooth, then search again');
      }
    }
    final found = <String, FoundPrinter>{};
    final sub = FlutterBluePlus.onScanResults.listen((results) {
      for (final r in results) {
        final name = r.device.platformName.isNotEmpty ? r.device.platformName : r.advertisementData.advName;
        if (name.isEmpty) continue; // printers always advertise a name
        found[r.device.remoteId.str] = FoundPrinter(r.device.remoteId.str, name, r.rssi);
      }
    });
    try {
      await FlutterBluePlus.startScan(timeout: Duration(seconds: seconds), androidCheckLocationServices: false);
      await FlutterBluePlus.isScanning.where((s) => s == false).first.timeout(Duration(seconds: seconds + 4));
    } finally {
      await sub.cancel();
      try {
        await FlutterBluePlus.stopScan();
      } catch (_) {}
    }
    final list = found.values.toList()..sort((a, b) => b.rssi.compareTo(a.rssi));
    // Likely printers first.
    bool looksLikePrinter(FoundPrinter p) =>
        RegExp(r'print|pos|psf|sc5|mtp|58|80|bt-?\d|xp|goj|rpp|pt-|mpt|thermal|receipt', caseSensitive: false).hasMatch(p.name);
    list.sort((a, b) => (looksLikePrinter(b) ? 1 : 0) - (looksLikePrinter(a) ? 1 : 0));
    return list;
  }

  // Write characteristics used by common thermal printers (service -> characteristic).
  static final _known = <String, String>{
    '000018f0-0000-1000-8000-00805f9b34fb': '00002af1-0000-1000-8000-00805f9b34fb',
    '0000ff00-0000-1000-8000-00805f9b34fb': '0000ff02-0000-1000-8000-00805f9b34fb',
    'e7810a71-73ae-499d-8c15-faa9aef0c3f2': 'bef8d6c9-9c21-4c9e-b632-bd58c1009f9f',
    '49535343-fe7d-4ae5-8fa9-9fafd205e455': '49535343-8841-43f4-a8d4-ecbe34729bb3',
    '0000fee7-0000-1000-8000-00805f9b34fb': '0000fec7-0000-1000-8000-00805f9b34fb',
  };

  static BluetoothDevice? _device;
  static BluetoothCharacteristic? _char;

  /// Sends ESC/POS bytes to the BLE printer [id] (its Bluetooth address on Android).
  static Future<void> printBle(String id, List<int> bytes) async {
    if (!await ensurePermissions()) {
      throw Exception('Allow "Nearby devices" (Bluetooth) for Servora in phone Settings, then try again');
    }
    var dev = _device;
    if (dev == null || dev.remoteId.str != id || !dev.isConnected || _char == null) {
      await disconnect();
      dev = BluetoothDevice.fromId(id);
      try {
        await dev.connect(timeout: const Duration(seconds: 10));
      } catch (_) {
        throw Exception('Could not connect to the printer - is it switched on and close by?');
      }
      _char = await _findWriter(dev);
      if (_char == null) {
        await dev.disconnect();
        throw Exception('This Bluetooth device does not accept printing');
      }
      _device = dev;
    }
    final ch = _char!;
    final noResponse = ch.properties.writeWithoutResponse;
    // Small pieces with a short pause: cheap printers drop data that arrives too fast.
    final size = (dev.mtuNow - 3).clamp(20, 180);
    try {
      for (var i = 0; i < bytes.length; i += size) {
        final end = (i + size < bytes.length) ? i + size : bytes.length;
        await ch.write(bytes.sublist(i, end), withoutResponse: noResponse);
        if (noResponse) await Future<void>.delayed(const Duration(milliseconds: 15));
      }
    } catch (e) {
      await disconnect();
      throw Exception('Printer stopped receiving - try again');
    }
  }

  static Future<BluetoothCharacteristic?> _findWriter(BluetoothDevice dev) async {
    final services = await dev.discoverServices();
    bool canWrite(BluetoothCharacteristic c) => c.properties.write || c.properties.writeWithoutResponse;
    for (final s in services) {
      final want = _known[s.uuid.str128.toLowerCase()];
      if (want == null) continue;
      for (final c in s.characteristics) {
        if (c.uuid.str128.toLowerCase() == want && canWrite(c)) return c;
      }
      for (final c in s.characteristics) {
        if (canWrite(c)) return c;
      }
    }
    // Unknown printer: first writable characteristic outside the standard Bluetooth services.
    for (final s in services) {
      final u = s.uuid.str128.toLowerCase();
      if (u.startsWith('00001800') || u.startsWith('00001801') || u.startsWith('0000180a')) continue;
      for (final c in s.characteristics) {
        if (canWrite(c)) return c;
      }
    }
    return null;
  }

  static Future<void> disconnect() async {
    final d = _device;
    _device = null;
    _char = null;
    if (d != null) {
      try {
        await d.disconnect();
      } catch (_) {}
    }
  }
}
