import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';

import '../models/ops.dart';
import 'api_client.dart';
import 'config.dart';
import 'json.dart';

/// "Print from this device": polls queued print jobs and sends the raw
/// ESC/POS bytes to LAN printers (TCP 9100) or a paired Bluetooth printer,
/// then acknowledges each job.
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

  /// Starts / stops polling to match the "Print from this device" toggle.
  void _apply() {
    final want = _config.printFromDevice && _api.auth.isLoggedIn && _api.auth.restaurantId != null;
    if (want && _timer == null) {
      _timer = Timer.periodic(const Duration(seconds: 4), (_) => poll());
      poll();
      notifyListeners();
    } else if (!want && _timer != null) {
      _timer?.cancel();
      _timer = null;
      notifyListeners();
    }
  }

  void refreshState() => _apply();

  Future<void> poll() async {
    if (_busy) return;
    _busy = true;
    try {
      final rows = listOf(await _api.get('/print-jobs', query: {'status': 'queued'}));
      lastPoll = DateTime.now();
      final jobs = rows.map((e) => PrintJob.fromJson(asMap(e))).where(canHandle).toList()
        ..sort((a, b) => a.id.compareTo(b.id));
      for (final job in jobs) {
        await printAndAck(job);
      }
    } catch (e) {
      lastError = errorText(e);
    } finally {
      _busy = false;
      notifyListeners();
    }
  }

  /// Jobs this device can reach. USB / serial / cloud devices are left to the
  /// desktop hardware agent.
  bool canHandle(PrintJob job) {
    switch (job.connection) {
      case 'network':
        return (job.address ?? '').isNotEmpty || _config.fallbackLanPrinter.isNotEmpty;
      case 'bluetooth':
        return (job.address ?? '').isNotEmpty || _config.btPrinterMac.isNotEmpty;
      case 'browser':
      case null:
        return _config.btPrinterMac.isNotEmpty || _config.fallbackLanPrinter.isNotEmpty;
      default:
        return false;
    }
  }

  Future<void> printAndAck(PrintJob job) async {
    try {
      await printJob(job);
      printedCount++;
      lastError = null;
      await _api.post('/print-jobs/${job.id}/ack', {'ok': true});
    } on NetworkException {
      rethrow;
    } catch (e) {
      lastError = '#${job.id}: $e';
      await _api.post('/print-jobs/${job.id}/ack', {'ok': false, 'error': e.toString()});
    }
  }

  Future<void> printJob(PrintJob job) async {
    final bytes = bytesFor(job);
    final address = (job.address ?? '').trim();
    switch (job.connection) {
      case 'network':
        await sendToLan(address.isNotEmpty ? address : _config.fallbackLanPrinter, bytes);
        return;
      case 'bluetooth':
        await sendToBluetooth(address.isNotEmpty ? address : _config.btPrinterMac, bytes);
        return;
      default:
        if (_config.btPrinterMac.isNotEmpty) {
          await sendToBluetooth(_config.btPrinterMac, bytes);
        } else {
          await sendToLan(_config.fallbackLanPrinter, bytes);
        }
    }
  }

  static List<int> bytesFor(PrintJob job) {
    if (job.escposB64.isNotEmpty) return base64Decode(job.escposB64);
    return textToEscPos(job.text);
  }

  /// Fallback rendering when the server sent only plain text.
  static List<int> textToEscPos(String text) {
    final ascii = text.codeUnits.map((c) => c == 0x20B9 ? 0x52 : (c < 128 ? c : 0x3F)).toList(); // ₹ -> R
    return <int>[0x1B, 0x40, ...ascii, 0x0A, 0x0A, 0x0A, 0x0A, 0x1D, 0x56, 0x00];
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

  static Future<void> sendToBluetooth(String mac, List<int> bytes) async {
    if (mac.isEmpty) throw Exception('No Bluetooth printer selected');
    final connected = await PrintBluetoothThermal.connectionStatus;
    if (!connected) {
      final ok = await PrintBluetoothThermal.connect(macPrinterAddress: mac);
      if (!ok) throw Exception('Could not connect to Bluetooth printer');
    }
    final ok = await PrintBluetoothThermal.writeBytes(bytes);
    if (!ok) throw Exception('Bluetooth printer did not accept data');
  }

  Future<void> testPrint() async {
    final job = PrintJob(
      id: 0,
      kind: 'test',
      title: 'Test',
      text: '      SERVORA\n  Test print OK\n${DateTime.now()}\n',
      escposB64: '',
      status: 'queued',
      error: '',
      deviceName: null,
      connection: null,
      address: null,
      createdAt: DateTime.now(),
    );
    await printJob(job);
  }

  @override
  void dispose() {
    _timer?.cancel();
    _config.removeListener(_apply);
    _api.auth.removeListener(_apply);
    super.dispose();
  }
}
