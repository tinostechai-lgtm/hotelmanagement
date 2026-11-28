import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../models/ops.dart';
import 'api_client.dart';
import 'bt_printers.dart';
import 'config.dart';
import 'json.dart';

/// Result of a direct print.
class PrintResult {
  const PrintResult(this.printed, [this.error]);
  final int printed;
  final String? error;
}

/// Direct printing from this phone / tablet.
///
/// * Pressing KOT / Bill / Print prints straight away on this phone's own printer
///   ([printNow]) - no waiting, no share / copy step.
/// * Optionally ("Print orders from other phones") it also prints KOTs and bills
///   sent from other phones while the app is open ([poll]).
///
/// Every job is claimed on the server before printing, so two phones never print
/// the same ticket, and it is laid out for this phone's printer (paper width, text size).
class PrintService extends ChangeNotifier {
  PrintService(this._config, this._api) {
    _config.addListener(_apply);
    _api.auth.addListener(_apply);
  }

  final AppConfig _config;
  final ApiClient _api;
  Timer? _timer;
  bool _busy = false;
  int printedCount = 0;
  String? lastError;
  DateTime? lastPoll;

  bool get running => _timer != null;

  /// Starts / stops printing for other phones to match the toggle.
  void _apply() {
    final want = _config.printFromDevice && _config.hasMainPrinter && _api.auth.isLoggedIn && _api.auth.restaurantId != null;
    if (want && _timer == null) {
      // Printer phone: check for new KOTs / bills every 2 seconds and keep the screen on
      // so Android doesn't pause the app.
      _timer = Timer.periodic(const Duration(seconds: 2), (_) => poll());
      poll();
      WakelockPlus.enable().catchError((_) {});
      notifyListeners();
    } else if (!want && _timer != null) {
      _timer?.cancel();
      _timer = null;
      WakelockPlus.disable().catchError((_) {});
      notifyListeners();
    }
  }

  void refreshState() => _apply();

  bool _wants(String kind) =>
      _config.targetFor(kind) != null && (kind == 'kot' ? _config.printKotHere : kind == 'bill' ? _config.printBillHere : true);

  /// Prints the fresh KOT / bill of [orderId] on this phone's printer right away.
  /// Returns how many tickets were printed (0 when this phone doesn't print that kind).
  Future<PrintResult> printNow(int? orderId, String kind) async {
    if (orderId == null || !_config.autoPrint || !_wants(kind)) return const PrintResult(0);
    try {
      final rows = listOf(await _api.get('/print-jobs',
          query: {'status': 'queued', 'order': '$orderId', 'kind': kind, 'since': '180'}));
      final jobs = rows.map((e) => PrintJob.fromJson(asMap(e))).toList()..sort((a, b) => a.id.compareTo(b.id));
      return await _printJobs(jobs);
    } catch (e) {
      lastError = errorText(e);
      notifyListeners();
      return PrintResult(0, lastError);
    }
  }

  /// Prints tickets sent from other phones (only while "Print orders from other phones" is on).
  Future<void> poll() async {
    if (_busy) return;
    final kinds = [if (_wants('kot')) 'kot', if (_wants('bill')) 'bill'];
    if (kinds.isEmpty) return;
    _busy = true;
    try {
      final rows = listOf(await _api.get('/print-jobs',
          query: {'status': 'queued', 'kind': kinds.join(','), 'since': '300'}));
      lastPoll = DateTime.now();
      final jobs = rows.map((e) => PrintJob.fromJson(asMap(e))).toList()..sort((a, b) => a.id.compareTo(b.id));
      await _printJobs(jobs.take(10).toList()).timeout(const Duration(seconds: 90));
    } catch (e) {
      lastError = errorText(e);
    } finally {
      _busy = false;
      notifyListeners();
    }
  }

  /// Prints one job from the list again on this phone (re-queues it first if it was done / failed).
  Future<PrintResult> printAgain(PrintJob job) async {
    if (job.status != 'queued') await _api.post('/print-jobs/${job.id}/retry', const <String, dynamic>{});
    return _printJobs([job]);
  }

  Future<PrintResult> _printJobs(List<PrintJob> jobs) async {
    var printed = 0;
    String? error;
    for (final job in jobs) {
      final target = _config.targetFor(job.kind);
      if (target == null) continue;
      Map<String, dynamic> r;
      try {
        // Claim it (so no other phone prints it) and get it laid out for this printer - one call.
        r = asMap(await _api.post(
            '/print-jobs/${job.id}/claim?width=${_config.paperWidth}&size=${_config.textSize}', const <String, dynamic>{}));
      } on ApiException {
        continue; // another phone is printing it
      }
      try {
        final b64 = asStr(r['escpos_b64'], job.escposB64);
        final bytes = b64.isNotEmpty ? base64Decode(b64).toList() : textToEscPos(job.text, _config.textSize);
        await sendTo(target, bytes).timeout(const Duration(seconds: 30));
        printed++;
        printedCount++;
        lastError = null;
        unawaited(_api.post('/print-jobs/${job.id}/ack', {'ok': true}).catchError((_) => null));
      } on NetworkException {
        rethrow;
      } catch (e) {
        error = e is TimeoutException ? 'Printer did not respond' : e.toString().replaceFirst('Exception: ', '');
        lastError = error;
        try {
          await _api.post('/print-jobs/${job.id}/ack', {'ok': false, 'error': error});
        } catch (_) {}
      }
    }
    if (printed > 0 || error != null) notifyListeners();
    return PrintResult(printed, error);
  }

  static Future<void> _line = Future<void>.value();

  /// Sends bytes to 'bt:<mac>' or 'lan:<ip:port>'. One ticket at a time, so a KOT pressed on this
  /// phone and one arriving from another phone never get mixed on the paper.
  Future<void> sendTo(String target, List<int> bytes) {
    final done = _line.catchError((_) {}).then((_) {
      if (target.startsWith('ble:')) return BtPrinters.printBle(target.substring(4), bytes);
      if (target.startsWith('bt:')) return sendToBluetooth(target.substring(3), bytes);
      return sendToLan(target.substring(4), bytes);
    });
    _line = done.catchError((_) {});
    return done;
  }

  /// Fallback rendering when the server sent only plain text.
  static List<int> textToEscPos(String text, [String size = 'normal']) {
    final ascii = text.codeUnits.map((c) => c == 0x20B9 ? 0x52 : (c < 128 ? c : 0x3F)).toList(); // ₹ -> R
    final mode = size == 'xlarge' ? 0x11 : (size == 'large' ? 0x01 : 0x00);
    return <int>[0x1B, 0x40, 0x1D, 0x21, mode, ...ascii, 0x0A, 0x0A, 0x0A, 0x0A, 0x1D, 0x56, 0x00];
  }

  static Future<void> sendToLan(String address, List<int> bytes) async {
    if (address.isEmpty) throw Exception('No printer IP configured');
    final parts = address.split(':');
    final host = parts.first.trim();
    final port = parts.length > 1 ? int.tryParse(parts[1].trim()) ?? 9100 : 9100;
    final socket = await Socket.connect(host, port, timeout: const Duration(seconds: 5));
    try {
      socket.add(bytes);
      await socket.flush();
      await socket.close().timeout(const Duration(seconds: 3), onTimeout: () => null);
    } finally {
      socket.destroy();
    }
  }

  static String _connectedMac = '';

  static Future<void> sendToBluetooth(String mac, List<int> bytes) async {
    if (mac.isEmpty) throw Exception('No Bluetooth printer selected');
    // Android 12+: without "Nearby devices" permission the plugin never answers - ask for it.
    final allowed = await BtPrinters.ensurePermissions();
    if (!allowed) {
      throw Exception('Allow "Nearby devices" (Bluetooth) for Servora in phone Settings, then try again');
    }
    var connected = await PrintBluetoothThermal.connectionStatus
        .timeout(const Duration(seconds: 5), onTimeout: () => false);
    if (connected && _connectedMac != mac) {
      // Connected to the other printer (separate KOT / bill printers): switch.
      await PrintBluetoothThermal.disconnect.timeout(const Duration(seconds: 5), onTimeout: () => false);
      connected = false;
    }
    if (!connected) {
      final ok = await PrintBluetoothThermal.connect(macPrinterAddress: mac)
          .timeout(const Duration(seconds: 12), onTimeout: () => false);
      if (!ok) {
        // Many small "mobile printers" only talk Bluetooth Low Energy: try that before giving up.
        if (Platform.isAndroid) {
          try {
            await BtPrinters.printBle(mac, bytes);
            return;
          } catch (_) {}
        }
        throw Exception('Could not connect to the Bluetooth printer - switch it on, keep it close, '
            'and close any other printing app that may be using it');
      }
      _connectedMac = mac;
    }
    final ok = await PrintBluetoothThermal.writeBytes(bytes)
        .timeout(const Duration(seconds: 15), onTimeout: () => false);
    if (!ok) {
      _connectedMac = '';
      throw Exception('Bluetooth printer did not accept data');
    }
  }

  /// Test page for 'kot' or 'bill' printer, at the chosen paper width and text size.
  Future<void> testPrint([String kind = 'bill']) async {
    final target = _config.targetFor(kind);
    if (target == null) throw Exception('Choose a printer first');
    final cols = _config.paperWidth <= 58 ? 32 : 48;
    final w = _config.textSize == 'xlarge' ? cols ~/ 2 : cols;
    String row(String l, String r) => l.padRight(w - r.length) + r;
    final text = [
      'SERVORA',
      kind == 'kot' ? 'KOT printer test' : 'Bill printer test',
      '-' * w,
      row('2 x Masala Dosa', 'Rs.180'),
      row('1 x Filter Coffee', 'Rs.40'),
      '-' * w,
      'Paper ${_config.paperWidth} mm, ${_config.textSize} text',
      DateTime.now().toString().substring(0, 16),
    ].join('\n');
    await sendTo(target, textToEscPos(text, _config.textSize));
  }

  @override
  void dispose() {
    _timer?.cancel();
    _config.removeListener(_apply);
    _api.auth.removeListener(_apply);
    super.dispose();
  }
}
