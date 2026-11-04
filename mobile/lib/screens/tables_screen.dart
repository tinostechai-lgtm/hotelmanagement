import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/format.dart';
import '../core/json.dart';
import '../core/pos_data.dart';
import '../models/ops.dart';
import '../models/order.dart';
import '../widgets/common.dart';
import '../widgets/offline_banner.dart';
import 'order_screen.dart';

const tableStatusColors = <String, Color>{
  'free': Brand.success,
  'occupied': Brand.orangeDeep,
  'billed': Brand.info,
  'reserved': Color(0xFF8B5CF6),
  'cleaning': Color(0xFF94A3B8),
};

const tableStatusLabels = <String, String>{
  'free': 'Free',
  'occupied': 'Occupied',
  'billed': 'Billed',
  'reserved': 'Reserved',
  'cleaning': 'Cleaning',
};

class TablesScreen extends StatefulWidget {
  const TablesScreen({super.key});

  @override
  State<TablesScreen> createState() => _TablesScreenState();
}

class _TablesScreenState extends State<TablesScreen> {
  Timer? _poll;
  Timer? _tick;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => context.read<PosData>().refreshTables());
    _poll = Timer.periodic(const Duration(seconds: 15), (_) {
      if (mounted) context.read<PosData>().refreshTables();
    });
    _tick = Timer.periodic(const Duration(seconds: 30), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    _tick?.cancel();
    super.dispose();
  }

  Future<void> _open(OrderTarget target) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => OrderScreen(target: target)));
    if (mounted) await context.read<PosData>().refreshTables();
  }

  Future<void> _tableMenu(DiningTable t) async {
    final api = context.read<ApiClient>();
    final data = context.read<PosData>();
    final status = await showSheet<String>(
      context,
      (ctx) => SheetFrame(
        title: 'Table ${t.name}',
        child: ListView(shrinkWrap: true, children: [
          for (final s in const ['free', 'reserved', 'cleaning'])
            ListTile(
              leading: CircleAvatar(radius: 8, backgroundColor: tableStatusColors[s]),
              title: Text('Mark as ${tableStatusLabels[s]}'),
              enabled: t.activeOrder == null,
              onTap: () => Navigator.pop(ctx, s),
            ),
          if (t.activeOrder != null)
            const ListTile(
              leading: Icon(Icons.info_outline),
              title: Text('Table has a running order — settle or move it first.'),
            ),
        ]),
      ),
    );
    if (status == null) return;
    try {
      await api.post('/tables/${t.id}/status', {'status': status});
      await data.refreshTables();
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  Future<void> _runningOrders() async {
    final api = context.read<ApiClient>();
    final picked = await showSheet<OrderSummary>(context, (ctx) => _RunningOrdersSheet(api: api));
    if (picked != null && mounted) {
      await _open(OrderTarget(orderType: picked.orderType, orderId: picked.id, title: '#${picked.number} · ${picked.label}'));
    }
  }

  Future<void> _roomService() async {
    final data = context.read<PosData>();
    final room = await showSheet<Room>(
      context,
      (ctx) => SheetFrame(
        title: 'Room service',
        child: GridView.count(
          shrinkWrap: true,
          padding: const EdgeInsets.all(16),
          crossAxisCount: MediaQuery.sizeOf(ctx).width > 600 ? 6 : 3,
          mainAxisSpacing: 10,
          crossAxisSpacing: 10,
          children: [
            for (final r in data.rooms)
              OutlinedButton(
                onPressed: () => Navigator.pop(ctx, r),
                style: OutlinedButton.styleFrom(
                  backgroundColor: r.isOccupied ? Brand.steam.withOpacity(0.5) : null,
                  padding: const EdgeInsets.all(6),
                ),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(r.number, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
                  if (r.guestName.isNotEmpty)
                    Text(r.guestName, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11)),
                ]),
              ),
          ],
        ),
      ),
    );
    if (room != null) {
      await _open(OrderTarget(orderType: 'room_service', roomId: room.id, title: 'Room ${room.number}'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final data = context.watch<PosData>();
    final areas = data.areas;
    final tabs = <String>['All', ...areas.map((a) => a.name)];
    return DefaultTabController(
      length: tabs.length,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Tables'),
          actions: [
            IconButton(tooltip: 'Running orders', icon: const Icon(Icons.receipt_long), onPressed: _runningOrders),
            IconButton(tooltip: 'Refresh', icon: const Icon(Icons.refresh), onPressed: data.refreshTables),
          ],
          bottom: tabs.length > 1
              ? TabBar(
                  isScrollable: true,
                  tabAlignment: TabAlignment.start,
                  labelStyle: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
                  tabs: [for (final t in tabs) Tab(text: t)],
                )
              : null,
        ),
        body: Column(children: [
          const OfflineBanner(),
          _QuickActions(
            onTakeaway: () => _open(const OrderTarget(orderType: 'takeaway', title: 'Takeaway')),
            onDelivery: () => _open(const OrderTarget(orderType: 'delivery', title: 'Delivery')),
            onRoom: data.rooms.isNotEmpty ? _roomService : null,
          ),
          const _Legend(),
          Expanded(
            child: data.tables.isEmpty
                ? const EmptyState(icon: Icons.table_restaurant, title: 'No tables yet', message: 'Add tables from the web dashboard.')
                : TabBarView(children: [
                    _TableGrid(tables: data.tables, onTap: _openTable, onLongPress: _tableMenu),
                    for (final a in areas)
                      _TableGrid(
                        tables: data.tables.where((t) => t.areaId == a.id).toList(),
                        onTap: _openTable,
                        onLongPress: _tableMenu,
                      ),
                  ]),
          ),
        ]),
      ),
    );
  }

  void _openTable(DiningTable t) {
    _open(OrderTarget(
      orderType: 'dine_in',
      tableId: t.id,
      orderId: t.activeOrder?.id,
      title: 'Table ${t.name}',
    ));
  }
}

class _QuickActions extends StatelessWidget {
  const _QuickActions({required this.onTakeaway, required this.onDelivery, this.onRoom});

  final VoidCallback onTakeaway;
  final VoidCallback onDelivery;
  final VoidCallback? onRoom;

  @override
  Widget build(BuildContext context) {
    Widget btn(String label, IconData icon, VoidCallback? onTap) => Expanded(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: OutlinedButton.icon(
              onPressed: onTap,
              icon: Icon(icon, color: Brand.orangeDeep),
              label: Text(label, overflow: TextOverflow.ellipsis),
              style: OutlinedButton.styleFrom(backgroundColor: Colors.white),
            ),
          ),
        );
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      child: Row(children: [
        btn('Takeaway', Icons.shopping_bag_outlined, onTakeaway),
        btn('Delivery', Icons.delivery_dining_outlined, onDelivery),
        if (onRoom != null) btn('Room', Icons.hotel_outlined, onRoom),
      ]),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend();

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Row(children: [
        for (final e in tableStatusLabels.entries)
          Padding(
            padding: const EdgeInsets.only(right: 14),
            child: Row(children: [
              CircleAvatar(radius: 6, backgroundColor: tableStatusColors[e.key]),
              const SizedBox(width: 6),
              Text(e.value, style: const TextStyle(color: Brand.muted, fontWeight: FontWeight.w600)),
            ]),
          ),
      ]),
    );
  }
}

class _TableGrid extends StatelessWidget {
  const _TableGrid({required this.tables, required this.onTap, required this.onLongPress});

  final List<DiningTable> tables;
  final void Function(DiningTable) onTap;
  final void Function(DiningTable) onLongPress;

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: Provider.of<PosData>(context, listen: false).refreshTables,
      child: GridView.builder(
        padding: const EdgeInsets.fromLTRB(12, 6, 12, 24),
        gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
          maxCrossAxisExtent: 170,
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          childAspectRatio: 1,
        ),
        itemCount: tables.length,
        itemBuilder: (_, i) => _TableTile(table: tables[i], onTap: onTap, onLongPress: onLongPress),
      ),
    );
  }
}

class _TableTile extends StatelessWidget {
  const _TableTile({required this.table, required this.onTap, required this.onLongPress});

  final DiningTable table;
  final void Function(DiningTable) onTap;
  final void Function(DiningTable) onLongPress;

  @override
  Widget build(BuildContext context) {
    final status = table.effectiveStatus;
    final color = tableStatusColors[status] ?? Brand.muted;
    final o = table.activeOrder;
    final busy = o != null;
    return Material(
      color: busy ? color : Colors.white,
      borderRadius: BorderRadius.circular(20),
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: () => onTap(table),
        onLongPress: () => onLongPress(table),
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(20),
            border: busy ? null : Border.all(color: color, width: 2.5),
          ),
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Expanded(
                  child: Text(
                    table.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 26, fontWeight: FontWeight.w900, color: busy ? Colors.white : Brand.ink),
                  ),
                ),
                Icon(Icons.chair_outlined, size: 16, color: busy ? Colors.white70 : Brand.muted),
                Text(' ${o?.guests ?? table.seats}', style: TextStyle(color: busy ? Colors.white70 : Brand.muted)),
              ]),
              const Spacer(),
              if (o != null) ...[
                Text(Fmt.money(o.total),
                    style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w800)),
                Row(children: [
                  const Icon(Icons.timer_outlined, size: 14, color: Colors.white70),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      '${Fmt.elapsed(o.since ?? table.occupiedSince)} · ${o.items} items',
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: Colors.white70, fontSize: 12),
                    ),
                  ),
                ]),
              ] else
                Text(tableStatusLabels[status] ?? status, style: TextStyle(color: color, fontWeight: FontWeight.w800)),
            ],
          ),
        ),
      ),
    );
  }
}

class _RunningOrdersSheet extends StatefulWidget {
  const _RunningOrdersSheet({required this.api});

  final ApiClient api;

  @override
  State<_RunningOrdersSheet> createState() => _RunningOrdersSheetState();
}

class _RunningOrdersSheetState extends State<_RunningOrdersSheet> {
  List<OrderSummary>? _orders;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = asMap(await widget.api.get('/orders/live'));
      final list = listOf(d['orders']).map((e) => OrderSummary.fromJson(asMap(e))).toList();
      if (mounted) setState(() => _orders = list);
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final orders = _orders;
    return SheetFrame(
      title: 'Running orders',
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.7,
        child: _error != null
            ? EmptyState(icon: Icons.cloud_off, title: 'Could not load', message: _error)
            : orders == null
                ? const Center(child: CircularProgressIndicator())
                : orders.isEmpty
                    ? const EmptyState(icon: Icons.receipt_long, title: 'No open orders')
                    : ListView.separated(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        itemCount: orders.length,
                        separatorBuilder: (_, __) => const Divider(height: 1),
                        itemBuilder: (_, i) {
                          final o = orders[i];
                          return ListTile(
                            minVerticalPadding: 12,
                            leading: CircleAvatar(
                              backgroundColor: Brand.orangeDeep.withOpacity(0.12),
                              child: Icon(
                                switch (o.orderType) {
                                  'takeaway' => Icons.shopping_bag_outlined,
                                  'delivery' => Icons.delivery_dining,
                                  'room_service' => Icons.hotel,
                                  _ => Icons.table_restaurant,
                                },
                                color: Brand.orangeDeep,
                              ),
                            ),
                            title: Text('#${o.number} · ${o.label}', style: const TextStyle(fontWeight: FontWeight.w700)),
                            subtitle: Text(
                                '${o.statusDisplay} · ${o.itemCount} items${o.customerName.isNotEmpty ? ' · ${o.customerName}' : ''}'),
                            trailing: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                Text(Fmt.money(o.total), style: const TextStyle(fontWeight: FontWeight.w800)),
                                if (o.isPaid) const Pill('PAID', color: Brand.success),
                              ],
                            ),
                            onTap: () => Navigator.pop(context, o),
                          );
                        },
                      ),
      ),
    );
  }
}
