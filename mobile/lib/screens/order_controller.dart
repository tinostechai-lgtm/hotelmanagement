import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/json.dart';
import '../core/offline_queue.dart';
import '../models/cart.dart';
import '../models/order.dart';

/// What the order screen was opened for.
class OrderTarget {
  const OrderTarget({required this.orderType, this.tableId, this.roomId, this.orderId, this.title = ''});

  /// dine_in / takeaway / delivery / room_service
  final String orderType;
  final int? tableId;
  final int? roomId;
  final int? orderId;
  final String title;
}

/// State + server actions for one order (existing or about to be created).
class OrderController extends ChangeNotifier {
  OrderController({required this.api, required this.queue, required this.target}) {
    cart.addListener(notifyListeners);
    _ticker = Timer.periodic(const Duration(seconds: 10), (_) => _tick());
  }

  Timer? _ticker;
  int _ticks = 0;
  bool _disposed = false;

  /// Set when another attendant took this table over while it was open here.
  String? tableLost;

  int? get _lockTableId => target.orderType == 'dine_in' ? target.tableId : null;

  /// Every 10 s: refresh the order (live details from kitchen, cashier and other devices);
  /// every 30 s: renew this device's hold on the table.
  Future<void> _tick() async {
    if (_disposed) return;
    _ticks++;
    final tid = _lockTableId;
    if (tid != null && _ticks % 3 == 0) {
      try {
        await api.post('/tables/$tid/lock', const <String, dynamic>{});
      } on ApiException catch (e) {
        if (e.status == 409 && !_disposed) {
          tableLost = e.message;
          notifyListeners();
          return;
        }
      } catch (_) {}
    }
    final id = order?.id;
    if (id == null || busy || loading) return;
    try {
      final fresh = await api.get('/orders/$id');
      if (!_disposed && !busy) {
        _setOrder(fresh);
        notifyListeners();
      }
    } catch (_) {}
  }

  final ApiClient api;
  final OfflineQueue queue;
  final OrderTarget target;
  final Cart cart = Cart();

  final customerName = TextEditingController();
  final customerPhone = TextEditingController();
  final deliveryAddress = TextEditingController();

  Order? order;
  bool loading = false;
  bool busy = false;
  String? loadError;

  /// Seat assigned to newly added lines (dine-in), null = shared.
  int? seat;

  void setSeat(int? value) {
    seat = value;
    notifyListeners();
  }

  /// True after the order was stored in the offline queue.
  bool savedOffline = false;

  String get orderType => order?.orderType ?? target.orderType;
  bool get needsCustomer => orderType == 'takeaway' || orderType == 'delivery' || orderType == 'room_service';
  bool get isDineIn => orderType == 'dine_in';
  int? get roomId => order?.roomId ?? target.roomId;

  String get title {
    final o = order;
    if (o != null) return '#${o.number} · ${o.label}';
    return target.title.isNotEmpty ? target.title : 'New order';
  }

  Future<void> load() async {
    final id = target.orderId;
    if (id == null) return;
    loading = true;
    loadError = null;
    notifyListeners();
    try {
      _setOrder(await api.get('/orders/$id'));
      customerName.text = order!.customerName;
      customerPhone.text = order!.customerPhone;
      deliveryAddress.text = order!.deliveryAddress;
    } catch (e) {
      loadError = errorText(e);
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  void _setOrder(dynamic json) {
    order = Order.fromJson(asMap(json));
  }

  Future<T> _run<T>(Future<T> Function() fn) async {
    busy = true;
    notifyListeners();
    try {
      return await fn();
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  /// Set after staff confirm "Add again" for items the server says were just added by someone else.
  bool confirmDuplicate = false;

  // Idempotency key for the current batch of new items. Re-sending the same items (after a timeout,
  // a double tap or an offline replay) reuses it, so the server never adds them twice; a changed cart
  // gets a new key.
  String? _batchRef;
  String? _batchSig;

  String _refFor(List<Map<String, dynamic>> specs) {
    final sig = jsonEncode(specs);
    if (_batchRef == null || _batchSig != sig) {
      _batchRef = uuid4();
      _batchSig = sig;
    }
    return _batchRef!;
  }

  Map<String, dynamic> _itemsBody() {
    final specs = cart.toSpecs();
    return {'items': specs, 'send_kot': true, 'client_ref': _refFor(specs), if (confirmDuplicate) 'confirm_duplicate': true};
  }

  Map<String, dynamic> _createBody({required bool sendKot}) => {
        'order_type': target.orderType,
        'source': 'pos',
        if (target.tableId != null) 'table': target.tableId,
        if (target.roomId != null) 'room': target.roomId,
        'customer_name': customerName.text.trim(),
        'customer_phone': customerPhone.text.trim(),
        'delivery_address': deliveryAddress.text.trim(),
        'items': cart.toSpecs(),
        'send_kot': sendKot,
        'client_ref': _refFor(cart.toSpecs()),
        if (confirmDuplicate) 'confirm_duplicate': true,
      };

  Future<void> _queueOffline(Map<String, dynamic> body, {List<Map<String, dynamic>> payments = const [], bool complete = false}) async {
    await queue.enqueue(PendingOrder(
      clientRef: asStr(body['client_ref']),
      body: body,
      label: '${title.isEmpty ? 'Order' : title} · ${cart.count} items',
      estimatedTotal: cart.total + cart.estimatedTax,
      createdAt: DateTime.now(),
      payments: payments,
      complete: complete,
    ));
    cart.clear();
    savedOffline = true;
  }

  String? validateCustomer() {
    if (orderType == 'delivery') {
      if (customerPhone.text.trim().length < 10) return 'Enter the customer phone for delivery';
      if (deliveryAddress.text.trim().isEmpty) return 'Enter the delivery address';
    }
    return null;
  }

  /// Sends new lines to the kitchen (creating the order if needed).
  /// Returns a message for the user.
  Future<String> sendKot() => _run(() async {
        final invalid = validateCustomer();
        if (invalid != null) return invalid;
        final current = order;
        if (current == null) {
          if (cart.isEmpty) return 'Add items first';
          final body = _createBody(sendKot: true);
          try {
            _setOrder(await api.post('/orders', body));
          } on NetworkException {
            await _queueOffline(body);
            return 'Offline – order saved on this device and will sync automatically';
          }
          cart.clear();
          return 'KOT sent to kitchen';
        }
        if (cart.isEmpty) {
          if (!current.hasUnsentItems) return 'Nothing new to send';
          _setOrder(await api.post('/orders/${current.id}/kot', {'print': true}));
          return 'KOT sent to kitchen';
        }
        _setOrder(await api.post('/orders/${current.id}/items', _itemsBody()));
        cart.clear();
        return 'KOT sent to kitchen';
      });

  /// Makes sure everything in the cart is on the server. Returns false if
  /// the order could not be created (offline or empty).
  Future<bool> ensureSynced() async {
    if (order != null && cart.isEmpty) return true;
    await sendKot();
    return order != null && cart.isEmpty;
  }

  /// Pushes the cart to the server without queueing offline.
  /// Returns false when the server is unreachable.
  Future<bool> trySync() => _run(() async {
        try {
          final current = order;
          if (current == null) {
            if (cart.isEmpty) return true;
            _setOrder(await api.post('/orders', _createBody(sendKot: true)));
          } else if (!cart.isEmpty) {
            _setOrder(await api.post('/orders/${current.id}/items', _itemsBody()));
          }
        } on NetworkException {
          return false;
        }
        cart.clear();
        return true;
      });

  Future<void> _syncCustomer() async {
    final o = order;
    if (o == null || !needsCustomer) return;
    final name = customerName.text.trim();
    final phone = customerPhone.text.trim();
    final addr = deliveryAddress.text.trim();
    if (name == o.customerName && phone == o.customerPhone && addr == o.deliveryAddress) return;
    _setOrder(await api.patch('/orders/${o.id}', {
      'customer_name': name,
      'customer_phone': phone,
      if (orderType == 'delivery') 'delivery_address': addr,
    }));
  }

  Future<String> generateBill() async {
    final invalid = validateCustomer();
    if (invalid != null) return invalid;
    if (order == null && cart.isEmpty) return 'Add items first';
    if (!await ensureSynced()) {
      return savedOffline ? 'Saved offline – bill will be available after sync' : 'Could not create the order';
    }
    return _run(() async {
      await _syncCustomer();
      _setOrder(await api.post('/orders/${order!.id}/bill', {'print': true}));
      return 'Bill generated and sent to printer';
    });
  }

  Future<void> refresh() async {
    final o = order;
    if (o == null) return;
    _setOrder(await api.get('/orders/${o.id}'));
    notifyListeners();
  }

  Future<void> applyDiscount({double? percent, double? amount, String? coupon, String reason = ''}) => _run(() async {
        final body = <String, dynamic>{'reason': reason};
        if (coupon != null && coupon.isNotEmpty) {
          body['coupon'] = coupon;
        } else if (percent != null) {
          body['percent'] = percent;
        } else {
          body['amount'] = amount ?? 0;
        }
        _setOrder(await api.post('/orders/${order!.id}/discount', body));
      });

  /// mode: equal (with [parts]) or seat.
  Future<void> split(String mode, {int parts = 2}) => _run(() async {
        _setOrder(await api.post('/orders/${order!.id}/split', {'mode': mode, 'parts': parts}));
      });

  Future<void> pay(List<Map<String, dynamic>> payments) => _run(() async {
        await _syncCustomer();
        _setOrder(await api.post('/orders/${order!.id}/pay', {'payments': payments}));
      });

  /// Offline billing: queue the order together with its payment.
  Future<void> payOffline(List<Map<String, dynamic>> payments) => _run(() async {
        final body = _createBody(sendKot: true);
        await _queueOffline(body, payments: payments, complete: !isDineIn);
      });

  Future<void> setStatus(String status, {String reason = ''}) => _run(() async {
        _setOrder(await api.post('/orders/${order!.id}/status', {
          'status': status,
          if (reason.isNotEmpty) 'reason': reason,
        }));
      });

  Future<void> voidLine(OrderLine line, String reason) => _run(() async {
        _setOrder(await api.post('/orders/${order!.id}/items/${line.id}', {'void': true, 'reason': reason}));
      });

  Future<void> reprintBill() => _run(() async {
        await api.post('/orders/${order!.id}/print', {});
      });

  @override
  void dispose() {
    _disposed = true;
    _ticker?.cancel();
    final tid = _lockTableId;
    if (tid != null) {
      api.post('/tables/$tid/unlock', const <String, dynamic>{}).catchError((_) => null); // release the table
    }
    cart.removeListener(notifyListeners);
    cart.dispose();
    customerName.dispose();
    customerPhone.dispose();
    deliveryAddress.dispose();
    super.dispose();
  }
}
