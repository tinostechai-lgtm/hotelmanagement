import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/format.dart';
import '../core/json.dart';
import '../widgets/common.dart';
import '../widgets/offline_banner.dart';
import 'order_controller.dart' show OrderTarget;
import 'order_screen.dart';

/// Every open order with its items and kitchen status, refreshed every few seconds.
class LiveOrdersScreen extends StatefulWidget {
  const LiveOrdersScreen({super.key});

  @override
  State<LiveOrdersScreen> createState() => _LiveOrdersScreenState();
}

class _LiveOrdersScreenState extends State<LiveOrdersScreen> {
  static const _types = {'': 'All', 'dine_in': 'Dine-in', 'takeaway': 'Takeaway', 'delivery': 'Delivery', 'room_service': 'Room'};

  Timer? _timer;
  List<Map<String, dynamic>> _orders = [];
  String _type = '';
  String? _error;
  bool _loaded = false;
  DateTime? _updated;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 8), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final d = asMap(await context.read<ApiClient>().get('/orders/live', query: {'details': '1'}));
      if (!mounted) return;
      setState(() {
        _orders = listOf(d['orders']).map(asMap).toList();
        _error = null;
        _loaded = true;
        _updated = DateTime.now();
      });
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    }
  }

  Future<void> _open(Map<String, dynamic> o) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => OrderScreen(
        target: OrderTarget(
          orderType: asStr(o['order_type'], 'dine_in'),
          orderId: asInt(o['id']),
          tableId: asIntOrNull(o['table']),
          title: o['table_name'] != null ? 'Table ${o['table_name']}' : '#${o['number']} · ${o['label']}',
        ),
      ),
    ));
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final orders = _orders.where((o) => _type.isEmpty || o['order_type'] == _type).toList();
    final lines = orders.expand((o) => listOf(o['lines']).map(asMap)).toList();
    final inKitchen = lines.where((l) => l['status'] == 'sent' || l['status'] == 'preparing').length;
    final ready = lines.where((l) => l['status'] == 'ready').length;
    final value = orders.fold<double>(0, (s, o) => s + asDouble(o['total']));
    return Scaffold(
      appBar: AppBar(
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Live orders'),
          Text(_updated == null ? 'Loading…' : 'Live · updated ${Fmt.time(_updated)}',
              style: const TextStyle(fontSize: 13, color: Brand.steam, fontWeight: FontWeight.w600)),
        ]),
        actions: [IconButton(tooltip: 'Refresh', onPressed: _load, icon: const Icon(Icons.refresh_rounded))],
      ),
      body: Column(children: [
        const OfflineBanner(),
        SizedBox(
          height: 108,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
            child: Row(children: [
              Expanded(child: StatCard(label: 'Open', value: '${orders.length}', icon: Icons.receipt_long_rounded, color: Brand.info)),
              const SizedBox(width: 8),
              Expanded(child: StatCard(label: 'Kitchen', value: '$inKitchen', icon: Icons.soup_kitchen_rounded, color: Brand.warning)),
              const SizedBox(width: 8),
              Expanded(child: StatCard(label: 'Ready', value: '$ready', icon: Icons.room_service_rounded, color: Brand.success)),
              const SizedBox(width: 8),
              Expanded(child: StatCard(label: 'Running', value: Fmt.money(value), icon: Icons.payments_rounded, highlight: true)),
            ]),
          ),
        ),
        SizedBox(
          height: 56,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            children: [
              for (final e in _types.entries)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(label: Text(e.value), selected: _type == e.key, onSelected: (_) => setState(() => _type = e.key)),
                ),
            ],
          ),
        ),
        if (_error != null && !_loaded) Expanded(child: EmptyState(icon: Icons.cloud_off_rounded, title: 'Could not load', message: _error)),
        if (_loaded || _error == null)
          Expanded(
            child: !_loaded
                ? const Center(child: CircularProgressIndicator())
                : orders.isEmpty
                    ? const EmptyState(icon: Icons.coffee_rounded, title: 'No open orders right now')
                    : RefreshIndicator(
                        onRefresh: _load,
                        child: ListView.separated(
                          padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                          itemCount: orders.length,
                          separatorBuilder: (_, __) => const SizedBox(height: 12),
                          itemBuilder: (_, i) => _LiveOrderCard(order: orders[i], onTap: () => _open(orders[i])),
                        ),
                      ),
          ),
      ]),
    );
  }
}

class _LiveOrderCard extends StatelessWidget {
  const _LiveOrderCard({required this.order, required this.onTap});

  final Map<String, dynamic> order;
  final VoidCallback onTap;

  static const _status = <String, (String, Color)>{
    'new': ('Not sent', Brand.info),
    'sent': ('In kitchen', Brand.warning),
    'preparing': ('Preparing', Brand.warning),
    'ready': ('Ready', Brand.success),
    'served': ('Served', Brand.muted),
  };

  @override
  Widget build(BuildContext context) {
    final o = order;
    final lines = listOf(o['lines']).map(asMap).toList();
    final title = o['table_name'] != null ? 'Table ${o['table_name']}' : asStr(o['label']);
    final who = asStr(o['taken_by_name']);
    return PremiumCard(
      onTap: onTap,
      padding: EdgeInsets.zero,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
          decoration: const BoxDecoration(color: Color(0xFFF7F6FC), border: Border(bottom: BorderSide(color: Brand.line))),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900, color: Brand.ink)),
                const SizedBox(height: 2),
                Text('#${o['number']} · ${o['source_display']}${who.isNotEmpty ? ' · $who' : ''}',
                    style: const TextStyle(fontSize: 13, color: Brand.muted, fontWeight: FontWeight.w600)),
                if (asStr(o['customer_name']).isNotEmpty)
                  Text('${o['customer_name']} ${asStr(o['customer_phone'])}', style: const TextStyle(fontSize: 13, color: Brand.ink)),
              ]),
            ),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Pill(asStr(o['status_display']), color: Brand.info),
              const SizedBox(height: 4),
              Text(Fmt.elapsed(asDate(o['created_at'])), style: const TextStyle(fontSize: 13, color: Brand.muted, fontWeight: FontWeight.w600)),
            ]),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 6, 14, 6),
          child: Column(children: [
            if (lines.isEmpty) const Padding(padding: EdgeInsets.all(8), child: Text('No items yet', style: TextStyle(color: Brand.muted))),
            for (final l in lines)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  SizedBox(width: 36, child: Text('${l['qty']}×', style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15))),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(asStr(l['name']), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                      if (asStr(l['notes']).isNotEmpty) Text(asStr(l['notes']), style: const TextStyle(fontSize: 13, color: Brand.muted)),
                    ]),
                  ),
                  Pill(_status[l['status']]?.$1 ?? asStr(l['status']), color: _status[l['status']]?.$2 ?? Brand.muted),
                ]),
              ),
          ]),
        ),
        Container(
          padding: const EdgeInsets.fromLTRB(14, 8, 14, 10),
          decoration: const BoxDecoration(border: Border(top: BorderSide(color: Brand.line))),
          child: Row(children: [
            Text(Fmt.money(asDouble(o['total'])), style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
            const SizedBox(width: 8),
            if (o['is_paid'] == true) const Pill('PAID', color: Brand.success),
            const Spacer(),
            const Text('Open', style: TextStyle(color: Brand.orangeDeep, fontWeight: FontWeight.w800)),
            const Icon(Icons.chevron_right_rounded, color: Brand.orangeDeep),
          ]),
        ),
      ]),
    );
  }
}
