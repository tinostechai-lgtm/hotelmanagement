import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/format.dart';
import '../core/json.dart';
import '../models/ops.dart';
import '../widgets/common.dart';
import '../widgets/offline_banner.dart';

const deliveryStatusColors = <String, Color>{
  'unassigned': Brand.danger,
  'assigned': Brand.warning,
  'accepted': Brand.info,
  'picked_up': Color(0xFF8B5CF6),
  'delivered': Brand.success,
  'failed': Brand.muted,
};

class DeliveryOpsScreen extends StatefulWidget {
  const DeliveryOpsScreen({super.key});

  @override
  State<DeliveryOpsScreen> createState() => _DeliveryOpsScreenState();
}

class _DeliveryOpsScreenState extends State<DeliveryOpsScreen> {
  Timer? _poll;
  List<DeliveryTask> _tasks = [];
  List<Rider> _riders = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 10), (_) => _load());
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    try {
      final results = await Future.wait([
        api.get('/delivery/tasks', query: {'active': '1'}),
        api.get('/delivery/riders'),
      ]);
      if (!mounted) return;
      setState(() {
        _tasks = listOf(results[0]).map((e) => DeliveryTask.fromJson(asMap(e))).toList();
        _riders = listOf(results[1]).map((e) => Rider.fromJson(asMap(e))).toList();
        _error = null;
        _loading = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = errorText(e);
          _loading = false;
        });
      }
    }
  }

  Future<void> _assign(DeliveryTask t, {bool auto = false}) async {
    final api = context.read<ApiClient>();
    int? riderId;
    if (!auto) {
      final picked = await showSheet<Rider>(
        context,
        (ctx) => SheetFrame(
          title: 'Assign #${t.orderNumber}',
          child: ListView(shrinkWrap: true, padding: const EdgeInsets.only(bottom: 16), children: [
            if (_riders.isEmpty) const ListTile(title: Text('No riders. Add riders from the web dashboard.')),
            for (final r in [..._riders]..sort((a, b) => (b.isOnline ? 1 : 0) - (a.isOnline ? 1 : 0)))
              ListTile(
                minVerticalPadding: 14,
                leading: CircleAvatar(
                  backgroundColor: r.isOnline ? Brand.success : Brand.line,
                  child: const Icon(Icons.two_wheeler, color: Colors.white),
                ),
                title: Text(r.name, style: const TextStyle(fontWeight: FontWeight.w700)),
                subtitle: Text('${r.isOnline ? 'Online' : 'Offline'} · ${r.activeTasks} active · cash ${Fmt.money(r.cashInHand)}'),
                onTap: () => Navigator.pop(ctx, r),
              ),
          ]),
        ),
      );
      if (picked == null) return;
      riderId = picked.id;
    }
    try {
      await api.post('/delivery/tasks/${t.id}/assign', auto ? {'auto': true} : {'rider': riderId});
      if (mounted) toast(context, 'Rider assigned');
      await _load();
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  Future<void> _mark(DeliveryTask t, String action) async {
    final api = context.read<ApiClient>();
    try {
      await api.post('/delivery/tasks/${t.id}/$action', {});
      await _load();
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final online = _riders.where((r) => r.isOnline).length;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Delivery Ops'),
        actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh))],
      ),
      body: Column(children: [
        const OfflineBanner(),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
          child: SizedBox(height: 120, child: Row(children: [
            Expanded(child: StatCard(label: 'Active', value: '${_tasks.length}', icon: Icons.inventory_2_outlined)),
            const SizedBox(width: 10),
            Expanded(
              child: StatCard(
                label: 'Waiting',
                value: '${_tasks.where((t) => t.status == 'unassigned').length}',
                icon: Icons.warning_amber,
                highlight: _tasks.any((t) => t.status == 'unassigned'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(child: StatCard(label: 'Riders', value: '$online/${_riders.length}', icon: Icons.two_wheeler, color: Brand.teal)),
          ])),
        ),
        if (_error != null) Padding(padding: const EdgeInsets.all(8), child: Text(_error!, style: const TextStyle(color: Brand.danger))),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _load,
                  child: _tasks.isEmpty
                      ? ListView(children: const [
                          SizedBox(height: 60),
                          EmptyState(icon: Icons.delivery_dining, title: 'No active deliveries'),
                        ])
                      : ListView.builder(
                          padding: const EdgeInsets.all(12),
                          itemCount: _tasks.length,
                          itemBuilder: (_, i) => _TaskCard(
                            task: _tasks[i],
                            onAssign: () => _assign(_tasks[i]),
                            onAuto: () => _assign(_tasks[i], auto: true),
                            onPickup: () => _mark(_tasks[i], 'pickup'),
                          ),
                        ),
                ),
        ),
      ]),
    );
  }
}

class _TaskCard extends StatelessWidget {
  const _TaskCard({required this.task, required this.onAssign, required this.onAuto, required this.onPickup});

  final DeliveryTask task;
  final VoidCallback onAssign;
  final VoidCallback onAuto;
  final VoidCallback onPickup;

  @override
  Widget build(BuildContext context) {
    final t = task;
    final color = deliveryStatusColors[t.status] ?? Brand.muted;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      elevation: 0,
      color: Colors.white,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18), side: const BorderSide(color: Brand.line)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text('#${t.orderNumber}', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
            const SizedBox(width: 10),
            Pill(Fmt.titleCase(t.status), color: color),
            const Spacer(),
            Text(Fmt.money(t.total), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
            const SizedBox(width: 6),
            Pill(t.isPaid ? 'PAID' : 'COD', color: t.isPaid ? Brand.success : Brand.warning),
          ]),
          const SizedBox(height: 8),
          Text('${t.customerName.isEmpty ? 'Customer' : t.customerName} · ${t.customerPhone}',
              style: const TextStyle(fontWeight: FontWeight.w600)),
          if (t.address.isNotEmpty) Text(t.address, style: const TextStyle(color: Brand.muted)),
          if (t.items.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(t.items.join(', '), maxLines: 2, overflow: TextOverflow.ellipsis),
            ),
          const SizedBox(height: 10),
          Row(children: [
            Icon(Icons.two_wheeler, size: 18, color: t.riderName == null ? Brand.danger : Brand.ink),
            const SizedBox(width: 6),
            Expanded(
              child: Text(t.riderName ?? 'No rider yet',
                  style: TextStyle(fontWeight: FontWeight.w700, color: t.riderName == null ? Brand.danger : Brand.ink)),
            ),
            if (t.customerPhone.isNotEmpty)
              IconButton(
                tooltip: 'Call customer',
                onPressed: () => launchUrl(Uri(scheme: 'tel', path: t.customerPhone)),
                icon: const Icon(Icons.call_outlined),
              ),
          ]),
          const SizedBox(height: 6),
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (t.status == 'unassigned' || t.status == 'assigned') ...[
              FilledButton.icon(onPressed: onAuto, icon: const Icon(Icons.auto_awesome), label: const Text('Auto-assign')),
              OutlinedButton.icon(
                onPressed: onAssign,
                icon: const Icon(Icons.person_add_alt),
                label: Text(t.riderName == null ? 'Assign rider' : 'Reassign'),
              ),
            ],
            if (t.status == 'assigned' || t.status == 'accepted')
              OutlinedButton.icon(onPressed: onPickup, icon: const Icon(Icons.outbox_outlined), label: const Text('Picked up')),
          ]),
        ]),
      ),
    );
  }
}
