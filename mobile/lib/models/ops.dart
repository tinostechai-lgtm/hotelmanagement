import '../core/json.dart';

class Area {
  Area(this.id, this.name);

  final int id;
  final String name;
}

class TableOrderInfo {
  TableOrderInfo({
    required this.id,
    required this.number,
    required this.total,
    required this.status,
    required this.guests,
    required this.items,
    required this.since,
    required this.isPaid,
    required this.billed,
  });

  factory TableOrderInfo.fromJson(Map<String, dynamic> j) => TableOrderInfo(
        id: asInt(j['id']),
        number: asStr(j['number']),
        total: asDouble(j['total']),
        status: asStr(j['status']),
        guests: asInt(j['guests'], 1),
        items: asInt(j['items']),
        since: asDate(j['since']),
        isPaid: asBool(j['is_paid']),
        billed: asBool(j['billed']),
      );

  final int id;
  final String number;
  final double total;
  final String status;
  final int guests;
  final int items;
  final DateTime? since;
  final bool isPaid;
  final bool billed;
}

class DiningTable {
  DiningTable({
    required this.id,
    required this.name,
    required this.areaId,
    required this.areaName,
    required this.seats,
    required this.status,
    required this.activeOrder,
    required this.occupiedSince,
  });

  factory DiningTable.fromJson(Map<String, dynamic> j) => DiningTable(
        id: asInt(j['id']),
        name: asStr(j['name']),
        areaId: asIntOrNull(j['area']),
        areaName: asStr(j['area_name']),
        seats: asInt(j['seats'], 4),
        status: asStr(j['status'], 'free'),
        activeOrder: j['active_order'] is Map ? TableOrderInfo.fromJson(asMap(j['active_order'])) : null,
        occupiedSince: asDate(j['occupied_since']),
      );

  final int id;
  final String name;
  final int? areaId;
  final String areaName;
  final int seats;

  /// free / occupied / billed / reserved / cleaning
  final String status;
  final TableOrderInfo? activeOrder;
  final DateTime? occupiedSince;

  /// The status to display, reconciling the table flag with its open order.
  String get effectiveStatus {
    if (activeOrder != null) return activeOrder!.billed ? 'billed' : 'occupied';
    return status;
  }
}

class Room {
  Room({
    required this.id,
    required this.number,
    required this.roomType,
    required this.floor,
    required this.guestName,
    required this.isOccupied,
  });

  factory Room.fromJson(Map<String, dynamic> j) => Room(
        id: asInt(j['id']),
        number: asStr(j['number']),
        roomType: asStr(j['room_type']),
        floor: asStr(j['floor']),
        guestName: asStr(j['guest_name']),
        isOccupied: asBool(j['is_occupied']),
      );

  final int id;
  final String number;
  final String roomType;
  final String floor;
  final String guestName;
  final bool isOccupied;
}

class KotLine {
  KotLine({required this.id, required this.displayName, required this.quantity, required this.notes, required this.isVoid, required this.seat});

  factory KotLine.fromJson(Map<String, dynamic> j) => KotLine(
        id: asInt(j['id']),
        displayName: asStr(j['display_name'], asStr(j['name'])),
        quantity: asDouble(j['quantity'], 1),
        notes: asStr(j['notes']),
        isVoid: asBool(j['is_void']),
        seat: asIntOrNull(j['seat']),
      );

  final int id;
  final String displayName;
  final double quantity;
  final String notes;
  final bool isVoid;
  final int? seat;
}

class Kot {
  Kot({
    required this.id,
    required this.number,
    required this.status,
    required this.stationId,
    required this.stationName,
    required this.orderNumber,
    required this.orderLabel,
    required this.orderType,
    required this.orderNotes,
    required this.source,
    required this.createdAt,
    required this.lines,
  });

  factory Kot.fromJson(Map<String, dynamic> j) => Kot(
        id: asInt(j['id']),
        number: asInt(j['number']),
        status: asStr(j['status'], 'pending'),
        stationId: asIntOrNull(j['station']),
        stationName: asStr(j['station_name']),
        orderNumber: asStr(j['order_number']),
        orderLabel: asStr(j['order_label']),
        orderType: asStr(j['order_type']),
        orderNotes: asStr(j['order_notes']),
        source: asStr(j['source']),
        createdAt: asDate(j['created_at']) ?? DateTime.now(),
        lines: (j['lines'] is List ? j['lines'] as List : const []).map((e) => KotLine.fromJson(asMap(e))).toList(),
      );

  final int id;
  final int number;
  String status;
  final int? stationId;
  final String stationName;
  final String orderNumber;
  final String orderLabel;
  final String orderType;
  final String orderNotes;
  final String source;
  final DateTime createdAt;
  final List<KotLine> lines;
}

class DeliveryTask {
  DeliveryTask({
    required this.id,
    required this.orderId,
    required this.orderNumber,
    required this.orderStatus,
    required this.status,
    required this.customerName,
    required this.customerPhone,
    required this.address,
    required this.lat,
    required this.lng,
    required this.total,
    required this.isPaid,
    required this.riderId,
    required this.riderName,
    required this.items,
    required this.codAmount,
    required this.etaMinutes,
    required this.distanceKm,
  });

  factory DeliveryTask.fromJson(Map<String, dynamic> j) => DeliveryTask(
        id: asInt(j['id']),
        orderId: asInt(j['order_id'] ?? j['order']),
        orderNumber: asStr(j['order_number']),
        orderStatus: asStr(j['order_status']),
        status: asStr(j['status']),
        customerName: asStr(j['customer_name']),
        customerPhone: asStr(j['customer_phone']),
        address: asStr(j['address']),
        lat: asDoubleOrNull(j['lat']),
        lng: asDoubleOrNull(j['lng']),
        total: asDouble(j['total']),
        isPaid: asBool(j['is_paid']),
        riderId: asIntOrNull(j['rider']),
        riderName: j['rider_name']?.toString(),
        items: asStringList(j['items']),
        codAmount: asDouble(j['cod_amount']),
        etaMinutes: asInt(j['eta_minutes']),
        distanceKm: asDoubleOrNull(j['distance_km']),
      );

  final int id;
  final int orderId;
  final String orderNumber;
  final String orderStatus;

  /// unassigned / assigned / accepted / picked_up / delivered / failed
  final String status;
  final String customerName;
  final String customerPhone;
  final String address;
  final double? lat;
  final double? lng;
  final double total;
  final bool isPaid;
  final int? riderId;
  final String? riderName;
  final List<String> items;
  final double codAmount;
  final int etaMinutes;
  final double? distanceKm;
}

class Rider {
  Rider({
    required this.id,
    required this.name,
    required this.phone,
    required this.isOnline,
    required this.activeTasks,
    required this.cashInHand,
  });

  factory Rider.fromJson(Map<String, dynamic> j) => Rider(
        id: asInt(j['id']),
        name: asStr(j['name']),
        phone: asStr(j['phone']),
        isOnline: asBool(j['is_online']),
        activeTasks: asInt(j['active_tasks']),
        cashInHand: asDouble(j['cash_in_hand']),
      );

  final int id;
  final String name;
  final String phone;
  final bool isOnline;
  final int activeTasks;
  final double cashInHand;
}

class PrintJob {
  PrintJob({
    required this.id,
    required this.kind,
    required this.title,
    required this.text,
    required this.escposB64,
    required this.status,
    required this.error,
    required this.deviceName,
    required this.connection,
    required this.address,
    required this.createdAt,
  });

  factory PrintJob.fromJson(Map<String, dynamic> j) => PrintJob(
        id: asInt(j['id']),
        kind: asStr(j['kind']),
        title: asStr(j['title']),
        text: asStr(j['text']),
        escposB64: asStr(j['escpos_b64']),
        status: asStr(j['status']),
        error: asStr(j['error']),
        deviceName: j['device_name']?.toString(),
        connection: j['connection']?.toString(),
        address: j['address']?.toString(),
        createdAt: asDate(j['created_at']),
      );

  final int id;
  final String kind;
  final String title;
  final String text;
  final String escposB64;
  final String status;
  final String error;
  final String? deviceName;
  final String? connection;
  final String? address;
  final DateTime? createdAt;
}
