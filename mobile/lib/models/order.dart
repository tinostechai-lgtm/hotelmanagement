import '../core/json.dart';

const orderTypeLabels = <String, String>{
  'dine_in': 'Dine-in',
  'takeaway': 'Takeaway',
  'delivery': 'Delivery',
  'room_service': 'Room service',
};

class Order {
  Order({
    required this.id,
    required this.number,
    required this.orderType,
    required this.status,
    required this.statusDisplay,
    required this.label,
    required this.tableId,
    required this.roomId,
    required this.customerName,
    required this.customerPhone,
    required this.deliveryAddress,
    required this.notes,
    required this.subtotal,
    required this.discount,
    required this.serviceCharge,
    required this.tax,
    required this.extraCharges,
    required this.roundOff,
    required this.total,
    required this.paidAmount,
    required this.balance,
    required this.isPaid,
    required this.items,
    required this.bills,
    required this.nextStatuses,
    required this.createdAt,
  });

  factory Order.fromJson(Map<String, dynamic> j) {
    final total = asDouble(j['total']);
    final paid = asDouble(j['paid_amount']);
    return Order(
      id: asInt(j['id']),
      number: asStr(j['number']),
      orderType: asStr(j['order_type'], 'dine_in'),
      status: asStr(j['status']),
      statusDisplay: asStr(j['status_display'], asStr(j['status'])),
      label: asStr(j['label']),
      tableId: asIntOrNull(j['table']),
      roomId: asIntOrNull(j['room']),
      customerName: asStr(j['customer_name']),
      customerPhone: asStr(j['customer_phone']),
      deliveryAddress: asStr(j['delivery_address']),
      notes: asStr(j['notes']),
      subtotal: asDouble(j['subtotal']),
      discount: asDouble(j['discount']),
      serviceCharge: asDouble(j['service_charge']),
      tax: asDouble(j['tax']),
      extraCharges: asDouble(j['delivery_fee']) + asDouble(j['packaging_charge']) + asDouble(j['tip']),
      roundOff: asDouble(j['round_off']),
      total: total,
      paidAmount: paid,
      balance: j['balance'] != null ? asDouble(j['balance']) : (total - paid),
      isPaid: asBool(j['is_paid']),
      items: (j['items'] is List ? j['items'] as List : const []).map((e) => OrderLine.fromJson(asMap(e))).toList(),
      bills: (j['bills'] is List ? j['bills'] as List : const []).map((e) => Bill.fromJson(asMap(e))).toList(),
      nextStatuses: asStringList(j['next_statuses']),
      createdAt: asDate(j['created_at']),
    );
  }

  final int id;
  final String number;
  final String orderType;
  final String status;
  final String statusDisplay;
  final String label;
  final int? tableId;
  final int? roomId;
  final String customerName;
  final String customerPhone;
  final String deliveryAddress;
  final String notes;
  final double subtotal;
  final double discount;
  final double serviceCharge;
  final double tax;
  final double extraCharges;
  final double roundOff;
  final double total;
  final double paidAmount;
  final double balance;
  final bool isPaid;
  final List<OrderLine> items;
  final List<Bill> bills;
  final List<String> nextStatuses;
  final DateTime? createdAt;

  List<OrderLine> get liveItems => items.where((l) => !l.isVoid).toList();
  List<Bill> get activeBills => bills.where((b) => b.status != 'void').toList();
  bool get isClosed => status == 'completed' || status == 'cancelled';
  bool get hasUnsentItems => liveItems.any((l) => l.status == 'new');
}

class OrderLine {
  OrderLine({
    required this.id,
    required this.name,
    required this.displayName,
    required this.quantity,
    required this.unitPrice,
    required this.lineTotal,
    required this.status,
    required this.isVoid,
    required this.notes,
    required this.seat,
  });

  factory OrderLine.fromJson(Map<String, dynamic> j) => OrderLine(
        id: asInt(j['id']),
        name: asStr(j['name']),
        displayName: asStr(j['display_name'], asStr(j['name'])),
        quantity: asDouble(j['quantity'], 1),
        unitPrice: asDouble(j['unit_price']),
        lineTotal: asDouble(j['line_total']),
        status: asStr(j['status'], 'new'),
        isVoid: asBool(j['is_void']),
        notes: asStr(j['notes']),
        seat: asIntOrNull(j['seat']),
      );

  final int id;
  final String name;
  final String displayName;
  final double quantity;
  final double unitPrice;
  final double lineTotal;
  final String status;
  final bool isVoid;
  final String notes;
  final int? seat;
}

class Bill {
  Bill({
    required this.id,
    required this.number,
    required this.label,
    required this.total,
    required this.paid,
    required this.balance,
    required this.status,
  });

  factory Bill.fromJson(Map<String, dynamic> j) {
    final total = asDouble(j['total']);
    final paid = asDouble(j['paid']);
    return Bill(
      id: asInt(j['id']),
      number: asStr(j['number']),
      label: asStr(j['label']),
      total: total,
      paid: paid,
      balance: j['balance'] != null ? asDouble(j['balance']) : total - paid,
      status: asStr(j['status'], 'unpaid'),
    );
  }

  final int id;
  final String number;
  final String label;
  final double total;
  final double paid;
  final double balance;
  final String status;
}

/// Row from /api/orders/live (OrderListSerializer).
class OrderSummary {
  OrderSummary({
    required this.id,
    required this.number,
    required this.orderType,
    required this.status,
    required this.statusDisplay,
    required this.label,
    required this.customerName,
    required this.total,
    required this.isPaid,
    required this.itemCount,
    required this.tableId,
    required this.roomId,
    required this.createdAt,
  });

  factory OrderSummary.fromJson(Map<String, dynamic> j) => OrderSummary(
        id: asInt(j['id']),
        number: asStr(j['number']),
        orderType: asStr(j['order_type']),
        status: asStr(j['status']),
        statusDisplay: asStr(j['status_display']),
        label: asStr(j['label']),
        customerName: asStr(j['customer_name']),
        total: asDouble(j['total']),
        isPaid: asBool(j['is_paid']),
        itemCount: asInt(j['item_count']),
        tableId: asIntOrNull(j['table']),
        roomId: asIntOrNull(j['room']),
        createdAt: asDate(j['created_at']),
      );

  final int id;
  final String number;
  final String orderType;
  final String status;
  final String statusDisplay;
  final String label;
  final String customerName;
  final double total;
  final bool isPaid;
  final int itemCount;
  final int? tableId;
  final int? roomId;
  final DateTime? createdAt;
}
