import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';

import '../models/ops.dart';
import 'api_client.dart';
import 'json.dart';

/// Rider mode state. Lives app-wide so location pings continue while the
/// rider moves between screens.
class RiderService extends ChangeNotifier {
  RiderService(this._api);

  final ApiClient _api;
  Timer? _pingTimer;
  Timer? _pollTimer;

  bool loading = false;
  String? error;
  bool notRider = false;
  Rider? rider;
  List<DeliveryTask> tasks = [];
  int unsettled = 0;
  double cashInHand = 0;
  Map<String, dynamic> restaurant = {};
  Position? lastPosition;
  DateTime? lastPing;

  bool get isOnline => rider?.isOnline ?? false;

  Future<void> refresh() async {
    loading = tasks.isEmpty && rider == null;
    notifyListeners();
    try {
      final d = asMap(await _api.get('/rider'));
      rider = Rider.fromJson(asMap(d['rider']));
      tasks = listOf(d['tasks']).map((e) => DeliveryTask.fromJson(asMap(e))).toList();
      unsettled = asInt(d['unsettled_deliveries']);
      cashInHand = asDouble(d['cash_in_hand']);
      restaurant = asMap(d['restaurant']);
      notRider = false;
      error = null;
      _syncTimers();
    } on ApiException catch (e) {
      notRider = e.status == 403;
      error = e.message;
    } catch (e) {
      error = errorText(e);
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> setOnline(bool online) async {
    if (online) {
      final ok = await ensureLocationPermission();
      if (!ok) {
        error = 'Location permission is needed to go online.';
        notifyListeners();
        return;
      }
    }
    await _api.post('/rider', {'action': online ? 'online' : 'offline'});
    await refresh();
    if (online) await ping();
  }

  Future<bool> ensureLocationPermission() async {
    if (!await Geolocator.isLocationServiceEnabled()) return false;
    var p = await Geolocator.checkPermission();
    if (p == LocationPermission.denied) p = await Geolocator.requestPermission();
    return p == LocationPermission.always || p == LocationPermission.whileInUse;
  }

  Future<void> ping() async {
    try {
      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 15)),
      );
      lastPosition = pos;
      await _api.post('/rider', {
        'action': 'ping',
        'lat': double.parse(pos.latitude.toStringAsFixed(6)),
        'lng': double.parse(pos.longitude.toStringAsFixed(6)),
      });
      lastPing = DateTime.now();
      notifyListeners();
    } catch (_) {
      // ignore single failed pings
    }
  }

  Future<void> act(String action, DeliveryTask task, {String? otp, double? codCollected, String? reason}) async {
    await _api.post('/rider', {
      'action': action,
      'task': task.id,
      if (otp != null) 'otp': otp,
      if (codCollected != null) 'cod_collected': codCollected,
      if (reason != null) 'reason': reason,
    });
    await refresh();
  }

  void _syncTimers() {
    if (isOnline) {
      _pingTimer ??= Timer.periodic(const Duration(seconds: 20), (_) => ping());
      _pollTimer ??= Timer.periodic(const Duration(seconds: 15), (_) => refresh());
    } else {
      _pingTimer?.cancel();
      _pingTimer = null;
      _pollTimer?.cancel();
      _pollTimer = null;
    }
  }

  void stop() {
    _pingTimer?.cancel();
    _pingTimer = null;
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  @override
  void dispose() {
    stop();
    super.dispose();
  }
}
