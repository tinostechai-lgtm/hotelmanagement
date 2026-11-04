import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/format.dart';
import '../core/json.dart';
import '../core/rider_service.dart';
import '../models/ops.dart';
import '../widgets/common.dart';
import '../widgets/offline_banner.dart';
import 'delivery_ops_screen.dart' show deliveryStatusColors;

class RiderScreen extends StatefulWidget {
  const RiderScreen({super.key});

  @override
  State<RiderScreen> createState() => _RiderScreenState();
}

class _RiderScreenState extends State<RiderScreen> {
  bool _toggling = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => context.read<RiderService>().refresh());
  }

  Future<void> _toggle(bool v) async {
    setState(() => _toggling = true);
    try {
      await context.read<RiderService>().setOnline(v);
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _toggling = false);
    }
  }

  Future<void> _run(Future<void> Function() fn, String ok) async {
    try {
      await fn();
      if (mounted) toast(context, ok);
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  Future<void> _navigate(DeliveryTask t) async {
    final dest = t.lat != null && t.lng != null ? '${t.lat},${t.lng}' : t.address;
    final uri = Uri.https('www.google.com', '/maps/dir/', {'api': '1', 'destination': dest, 'travelmode': 'driving'});
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication) && mounted) {
      toast(context, 'Could not open Maps', error: true);
    }
  }

  Future<void> _deliver(DeliveryTask t) async {
    final rider = context.read<RiderService>();
    final result = await showSheet<Map<String, dynamic>>(context, (_) => _DeliverSheet(task: t));
    if (result == null) return;
    await _run(
      () => rider.act('deliver', t, otp: result['otp'] as String?, codCollected: result['cod'] as double?),
      'Delivered! Great job.',
    );
  }

  Future<void> _fail(DeliveryTask t) async {
    final rider = context.read<RiderService>();
    final ctl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Could not deliver?'),
        content: TextField(controller: ctl, decoration: const InputDecoration(labelText: 'Reason (e.g. customer not reachable)')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Back')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Mark failed')),
        ],
      ),
    );
    final reason = ctl.text.trim();
    ctl.dispose();
    if (ok == true) await _run(() => rider.act('fail', t, reason: reason), 'Marked as failed');
  }

  @override
  Widget build(BuildContext context) {
    final r = context.watch<RiderService>();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Rider'),
        actions: [IconButton(onPressed: r.refresh, icon: const Icon(Icons.refresh))],
      ),
      body: Column(children: [
        const OfflineBanner(),
        Expanded(
          child: r.notRider
              ? EmptyState(
                  icon: Icons.two_wheeler,
                  title: 'Not registered as a rider',
                  message: r.error ?? 'Ask your manager to link your login to a rider profile.',
                )
              : r.loading
                  ? const Center(child: CircularProgressIndicator())
                  : RefreshIndicator(
                      onRefresh: r.refresh,
                      child: ListView(padding: const EdgeInsets.all(16), children: [
                        _OnlineCard(service: r, busy: _toggling, onChanged: _toggle),
                        const SizedBox(height: 12),
                        Row(children: [
                          Expanded(child: StatCard(label: 'Cash in hand', value: Fmt.money(r.cashInHand), icon: Icons.account_balance_wallet_outlined)),
                          const SizedBox(width: 10),
                          Expanded(child: StatCard(label: 'Unsettled drops', value: '${r.unsettled}', icon: Icons.task_alt)),
                        ]),
                        if (r.error != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 10),
                            child: Text(r.error!, style: const TextStyle(color: Brand.danger)),
                          ),
                        const SectionTitle('My deliveries'),
                        if (r.tasks.isEmpty)
                          EmptyState(
                            icon: Icons.inbox_outlined,
                            title: r.isOnline ? 'Waiting for orders' : 'You are offline',
                            message: r.isOnline ? 'New deliveries appear here automatically.' : 'Go online to receive deliveries.',
                          ),
                        for (final t in r.tasks)
                          _RiderTaskCard(
                            task: t,
                            onCall: () => launchUrl(Uri(scheme: 'tel', path: t.customerPhone)),
                            onNavigate: () => _navigate(t),
                            onAccept: () => _run(() => r.act('accept', t), 'Accepted'),
                            onPickup: () => _run(() => r.act('pickup', t), 'Picked up – drive safe!'),
                            onDeliver: () => _deliver(t),
                            onFail: () => _fail(t),
                          ),
                      ]),
                    ),
        ),
      ]),
    );
  }
}

class _OnlineCard extends StatelessWidget {
  const _OnlineCard({required this.service, required this.busy, required this.onChanged});

  final RiderService service;
  final bool busy;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final online = service.isOnline;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        gradient: online ? const LinearGradient(colors: [Color(0xFF34D399), Brand.success]) : Brand.inkGradient,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(children: [
        Icon(online ? Icons.wifi_tethering : Icons.portable_wifi_off, color: Colors.white, size: 36),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(online ? 'You are online' : 'You are offline',
                style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w900)),
            Text(
              online
                  ? (service.lastPing != null ? 'Location shared ${Fmt.elapsed(service.lastPing)} ago' : 'Sharing location…')
                  : 'Go online to start receiving deliveries',
              style: const TextStyle(color: Colors.white70),
            ),
          ]),
        ),
        busy
            ? const SizedBox(width: 28, height: 28, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 3))
            : Transform.scale(
                scale: 1.3,
                child: Switch(
                  value: online,
                  activeColor: Colors.white,
                  activeTrackColor: Colors.white38,
                  onChanged: onChanged,
                ),
              ),
      ]),
    );
  }
}

class _RiderTaskCard extends StatelessWidget {
  const _RiderTaskCard({
    required this.task,
    required this.onCall,
    required this.onNavigate,
    required this.onAccept,
    required this.onPickup,
    required this.onDeliver,
    required this.onFail,
  });

  final DeliveryTask task;
  final VoidCallback onCall;
  final VoidCallback onNavigate;
  final VoidCallback onAccept;
  final VoidCallback onPickup;
  final VoidCallback onDeliver;
  final VoidCallback onFail;

  @override
  Widget build(BuildContext context) {
    final t = task;
    final collect = t.isPaid ? 0.0 : (t.codAmount > 0 ? t.codAmount : t.total);
    final Widget primary = switch (t.status) {
      'assigned' => GradientButton(label: 'Accept delivery', icon: Icons.check, onPressed: onAccept),
      'accepted' => GradientButton(label: 'Picked up from restaurant', icon: Icons.outbox, onPressed: onPickup),
      _ => GradientButton(label: 'Deliver (enter OTP)', icon: Icons.verified_outlined, onPressed: onDeliver),
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Brand.line),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Text('#${t.orderNumber}', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
          const SizedBox(width: 10),
          Pill(Fmt.titleCase(t.status), color: deliveryStatusColors[t.status] ?? Brand.muted),
          const Spacer(),
          if (t.distanceKm != null) Text('${t.distanceKm!.toStringAsFixed(1)} km', style: const TextStyle(color: Brand.muted)),
        ]),
        const SizedBox(height: 10),
        Text(t.customerName.isEmpty ? 'Customer' : t.customerName, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
        Text(t.address, style: const TextStyle(color: Brand.muted)),
        if (t.items.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(t.items.join('\n')),
        ],
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: (collect > 0 ? Brand.warning : Brand.success).withOpacity(0.12),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(
            collect > 0 ? 'Collect cash: ${Fmt.money(collect)}' : 'Prepaid – do not collect cash',
            style: TextStyle(fontWeight: FontWeight.w900, fontSize: 16, color: collect > 0 ? const Color(0xFFB45309) : Brand.success),
          ),
        ),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(
            child: OutlinedButton.icon(
              onPressed: t.customerPhone.isEmpty ? null : onCall,
              icon: const Icon(Icons.call),
              label: const Text('Call'),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: OutlinedButton.icon(onPressed: onNavigate, icon: const Icon(Icons.navigation_outlined), label: const Text('Navigate')),
          ),
        ]),
        const SizedBox(height: 10),
        primary,
        if (t.status == 'picked_up')
          TextButton(onPressed: onFail, child: const Text('Could not deliver', style: TextStyle(color: Brand.danger))),
      ]),
    );
  }
}

class _DeliverSheet extends StatefulWidget {
  const _DeliverSheet({required this.task});

  final DeliveryTask task;

  @override
  State<_DeliverSheet> createState() => _DeliverSheetState();
}

class _DeliverSheetState extends State<_DeliverSheet> {
  final _otp = TextEditingController();
  late final TextEditingController _cod;

  double get _due => widget.task.isPaid ? 0 : (widget.task.codAmount > 0 ? widget.task.codAmount : widget.task.total);

  @override
  void initState() {
    super.initState();
    _cod = TextEditingController(text: _due > 0 ? _due.toStringAsFixed(_due == _due.roundToDouble() ? 0 : 2) : '');
  }

  @override
  void dispose() {
    _otp.dispose();
    _cod.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SheetFrame(
      title: 'Deliver #${widget.task.orderNumber}',
      child: ListView(shrinkWrap: true, padding: const EdgeInsets.fromLTRB(20, 8, 20, 20), children: [
        const Text('Ask the customer for the 4-digit delivery OTP.', style: TextStyle(color: Brand.muted)),
        const SizedBox(height: 12),
        TextField(
          controller: _otp,
          autofocus: true,
          keyboardType: TextInputType.number,
          maxLength: 4,
          textAlign: TextAlign.center,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          onChanged: (_) => setState(() {}),
          style: const TextStyle(fontSize: 34, letterSpacing: 18, fontWeight: FontWeight.w900),
          decoration: const InputDecoration(counterText: '', hintText: '••••'),
        ),
        if (_due > 0) ...[
          const SizedBox(height: 12),
          TextField(
            controller: _cod,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
            decoration: InputDecoration(
              labelText: 'Cash collected',
              helperText: 'Order total ${Fmt.money(_due)}',
              prefixIcon: const Icon(Icons.payments_outlined),
            ),
          ),
        ],
        const SizedBox(height: 18),
        GradientButton(
          label: 'Confirm delivery',
          icon: Icons.check_circle,
          onPressed: _otp.text.length == 4
              ? () => Navigator.pop(context, <String, dynamic>{
                    'otp': _otp.text,
                    if (_due > 0) 'cod': asDouble(_cod.text, _due),
                  })
              : null,
        ),
      ]),
    );
  }
}
