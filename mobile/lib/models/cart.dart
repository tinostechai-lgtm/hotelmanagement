import 'package:flutter/foundation.dart';

import 'menu.dart';

/// A not-yet-sent line in the order screen.
class CartLine {
  CartLine({required this.item, this.variant, List<Addon>? addons, this.qty = 1, this.notes = '', this.seat})
      : addons = addons ?? <Addon>[];

  final MenuItem item;
  final Variant? variant;
  final List<Addon> addons;
  double qty;
  String notes;
  int? seat;

  double get unitPrice => (variant?.price ?? item.price) + addons.fold<double>(0, (s, a) => s + a.price);
  double get total => unitPrice * qty;

  String get title => variant == null ? item.name : '${item.name} (${variant!.name})';
  String get subtitle => addons.map((a) => a.name).join(', ');

  /// Identity used to merge repeated taps on the same configuration.
  String get signature {
    final ids = addons.map((a) => a.id).toList()..sort();
    return '${item.id}|${variant?.id}|${ids.join(",")}|$notes|$seat';
  }

  /// LineSpec payload for POST /api/orders and /api/orders/{id}/items.
  Map<String, dynamic> toSpec() => {
        'item_id': item.id,
        'quantity': qty == qty.roundToDouble() ? qty.toInt() : qty,
        if (variant != null) 'variant_id': variant!.id,
        if (addons.isNotEmpty) 'addon_ids': addons.map((a) => a.id).toList(),
        if (notes.isNotEmpty) 'notes': notes,
        if (seat != null) 'seat': seat,
      };
}

class Cart extends ChangeNotifier {
  final List<CartLine> lines = [];

  bool get isEmpty => lines.isEmpty;
  int get count => lines.fold<double>(0, (s, l) => s + l.qty).round();
  double get total => lines.fold<double>(0, (s, l) => s + l.total);

  /// Rough tax estimate from per-item tax percentages (server is authoritative).
  double get estimatedTax => lines.fold<double>(0, (s, l) => s + l.total * l.item.taxPercent / 100);

  void add(CartLine line) {
    for (final l in lines) {
      if (l.signature == line.signature) {
        l.qty += line.qty;
        notifyListeners();
        return;
      }
    }
    lines.add(line);
    notifyListeners();
  }

  void increment(CartLine l) {
    l.qty += 1;
    notifyListeners();
  }

  void decrement(CartLine l) {
    l.qty -= 1;
    if (l.qty <= 0) lines.remove(l);
    notifyListeners();
  }

  void remove(CartLine l) {
    lines.remove(l);
    notifyListeners();
  }

  void setNotes(CartLine l, String notes) {
    l.notes = notes;
    notifyListeners();
  }

  void clear() {
    lines.clear();
    notifyListeners();
  }

  List<Map<String, dynamic>> toSpecs() => lines.map((l) => l.toSpec()).toList();
}
