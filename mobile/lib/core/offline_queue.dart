import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'json.dart';

/// An order captured while the server was unreachable.
class PendingOrder {
  PendingOrder({
    required this.clientRef,
    required this.body,
    required this.label,
    required this.estimatedTotal,
    required this.createdAt,
    this.payments = const [],
    this.complete = false,
    this.serverId,
    this.paid = false,
    this.error,
  });

  factory PendingOrder.fromJson(Map<String, dynamic> j) => PendingOrder(
        clientRef: asStr(j['client_ref']),
        body: asMap(j['body']),
        label: asStr(j['label']),
        estimatedTotal: asDouble(j['estimated_total']),
        createdAt: asDate(j['created_at']) ?? DateTime.now(),
        payments: (j['payments'] is List ? j['payments'] as List : const []).map((e) => asMap(e)).toList(),
        complete: asBool(j['complete']),
        serverId: asIntOrNull(j['server_id']),
        paid: asBool(j['paid']),
        error: j['error']?.toString(),
      );

  final String clientRef;

  /// Body for POST /api/orders (already contains client_ref).
  final Map<String, dynamic> body;
  final String label;
  final double estimatedTotal;
  final DateTime createdAt;

  /// Optional payments for POST /api/orders/{id}/pay (offline billing).
  final List<Map<String, dynamic>> payments;

  /// Close the order (status=completed) after payment.
  final bool complete;

  // Sync progress so a retry never double-pays.
  int? serverId;
  bool paid;
  String? error;

  Map<String, dynamic> toJson() => {
        'client_ref': clientRef,
        'body': body,
        'label': label,
        'estimated_total': estimatedTotal,
        'created_at': createdAt.toIso8601String(),
        'payments': payments,
        'complete': complete,
        'server_id': serverId,
        'paid': paid,
        'error': error,
      };
}

/// Persists offline orders and replays them when connectivity returns.
/// The backend de-duplicates on `client_ref`, so replays are idempotent.
class OfflineQueue extends ChangeNotifier {
  OfflineQueue(this._prefs, this._api) {
    final raw = _prefs.getString(_key);
    if (raw != null) {
      try {
        items.addAll((jsonDecode(raw) as List).map((e) => PendingOrder.fromJson(asMap(e))));
      } catch (_) {
        // corrupted cache - ignore
      }
    }
    _api.online.addListener(_onConnectivity);
  }

  static const _key = 'offline.orders';

  final SharedPreferences _prefs;
  final ApiClient _api;
  final List<PendingOrder> items = [];
  Timer? _timer;
  bool syncing = false;

  int get pending => items.length;
  bool get online => _api.online.value;

  void start() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 20), (_) => sync());
  }

  void _onConnectivity() {
    notifyListeners();
    if (_api.online.value && items.isNotEmpty) sync();
  }

  Future<void> enqueue(PendingOrder order) async {
    items.add(order);
    await _save();
    notifyListeners();
  }

  Future<void> discard(PendingOrder order) async {
    items.remove(order);
    await _save();
    notifyListeners();
  }

  /// Pushes queued orders. Returns the number synced.
  Future<int> sync() async {
    if (syncing || items.isEmpty || _api.auth.access == null) return 0;
    syncing = true;
    notifyListeners();
    var done = 0;
    try {
      for (final p in List<PendingOrder>.from(items)) {
        try {
          if (p.serverId == null) {
            final order = asMap(await _api.post('/orders', p.body));
            p.serverId = asInt(order['id']);
            await _save();
          }
          if (p.payments.isNotEmpty && !p.paid) {
            await _api.post('/orders/${p.serverId}/pay', {'payments': p.payments});
            p.paid = true;
            await _save();
          }
          if (p.complete) {
            try {
              await _api.post('/orders/${p.serverId}/status', {'status': 'completed'});
            } on ApiException {
              // Already completed (dine-in auto-settles on full payment).
            }
          }
          items.remove(p);
          done++;
          await _save();
        } on NetworkException {
          break; // still offline: stop and retry on the next tick
        } on ApiException catch (e) {
          p.error = e.message;
          await _save();
        }
      }
    } finally {
      syncing = false;
      notifyListeners();
    }
    return done;
  }

  Future<void> _save() => _prefs.setString(_key, jsonEncode(items.map((e) => e.toJson()).toList()));

  @override
  void dispose() {
    _timer?.cancel();
    _api.online.removeListener(_onConnectivity);
    super.dispose();
  }
}
