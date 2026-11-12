import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/format.dart';
import '../core/json.dart';
import '../core/pos_data.dart';
import '../core/print_service.dart';
import '../widgets/common.dart';
import '../widgets/offline_banner.dart';

const _methods = {
  'cash': 'Cash', 'card': 'Card', 'upi': 'UPI', 'wallet': 'Wallet', 'razorpay': 'Online', 'cod': 'Cash on delivery',
  'room': 'Room', 'credit': 'Credit', 'loyalty': 'Loyalty',
};

/// Bill history: find any bill (paid ones included), view it and reprint it.
class BillsScreen extends StatefulWidget {
  const BillsScreen({super.key});

  @override
  State<BillsScreen> createState() => _BillsScreenState();
}

class _BillsScreenState extends State<BillsScreen> {
  DateTime _day = DateTime.now();
  final _q = TextEditingController();
  Timer? _debounce;
  List<Map<String, dynamic>>? _bills;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _q.dispose();
    _debounce?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    final q = _q.text.trim();
    try {
      final d = await context.read<ApiClient>().get('/bills', query: q.isNotEmpty ? {'q': q} : {'date': Fmt.isoDate(_day)});
      final rows = (d is Map ? listOf(d['results']) : listOf(d)).map(asMap).toList();
      if (mounted) setState(() => _bills = rows);
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    }
  }

  Future<void> _pickDay() async {
    final d = await showDatePicker(
      context: context,
      initialDate: _day,
      firstDate: DateTime(2024),
      lastDate: DateTime.now(),
    );
    if (d != null) {
      setState(() => _day = d);
      _load();
    }
  }

  void _shiftDay(int days) {
    final d = _day.add(Duration(days: days));
    if (d.isAfter(DateTime.now())) return;
    setState(() => _day = d);
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final bills = _bills;
    final total = (bills ?? const []).fold<double>(0, (s, b) => s + asDouble(b['total']));
    final today = Fmt.isoDate(_day) == Fmt.isoDate(DateTime.now());
    return Scaffold(
      appBar: AppBar(title: const Text('Bills'), actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh_rounded))]),
      body: Column(children: [
        const OfflineBanner(),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
          child: Row(children: [
            IconButton.filledTonal(onPressed: () => _shiftDay(-1), icon: const Icon(Icons.chevron_left_rounded)),
            Expanded(
              child: PremiumCard(
                onTap: _pickDay,
                padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 12),
                child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  const Icon(Icons.calendar_month_rounded, color: Brand.orangeDeep, size: 20),
                  const SizedBox(width: 8),
                  Text(today ? 'Today' : '${_day.day}/${_day.month}/${_day.year}',
                      style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
                ]),
              ),
            ),
            IconButton.filledTonal(onPressed: today ? null : () => _shiftDay(1), icon: const Icon(Icons.chevron_right_rounded)),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
          child: TextField(
            controller: _q,
            decoration: const InputDecoration(
              hintText: 'Search bill no., order no., table, phone',
              prefixIcon: Icon(Icons.search_rounded),
              isDense: true,
            ),
            onChanged: (_) {
              _debounce?.cancel();
              _debounce = Timer(const Duration(milliseconds: 350), _load);
            },
          ),
        ),
        if (bills != null && bills.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 2, 16, 4),
            child: Row(children: [
              Text('${bills.length} bills', style: const TextStyle(fontWeight: FontWeight.w700, color: Brand.muted)),
              const Spacer(),
              Text(Fmt.money(total), style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
            ]),
          ),
        Expanded(
          child: _error != null
              ? EmptyState(icon: Icons.cloud_off_rounded, title: 'Could not load bills', message: _error)
              : bills == null
                  ? const Center(child: CircularProgressIndicator())
                  : bills.isEmpty
                      ? const EmptyState(icon: Icons.receipt_long_rounded, title: 'No bills', message: 'Nothing billed on this day or for this search.')
                      : RefreshIndicator(
                          onRefresh: _load,
                          child: ListView.separated(
                            padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                            itemCount: bills.length,
                            separatorBuilder: (_, __) => const SizedBox(height: 10),
                            itemBuilder: (_, i) => _BillTile(bill: bills[i]),
                          ),
                        ),
        ),
      ]),
    );
  }
}

class _BillTile extends StatelessWidget {
  const _BillTile({required this.bill});

  final Map<String, dynamic> bill;

  @override
  Widget build(BuildContext context) {
    final b = bill;
    final status = asStr(b['status']);
    final paidBy = listOf(b['payments']).map(asMap).where((p) => p['status'] == 'success').map((p) => _methods[p['method']] ?? asStr(p['method'])).toSet().join(', ');
    return PremiumCard(
      onTap: () => showSheet<void>(context, (_) => BillSheet(bill: b)),
      child: Row(children: [
        IconBubble(Icons.receipt_long_rounded, color: status == 'paid' ? Brand.success : Brand.warning),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(asStr(b['number']), style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
            Text('${b['order_label']} · #${b['order_number']}', maxLines: 1, overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: Brand.muted, fontWeight: FontWeight.w600)),
            Text('${Fmt.time(asDate(b['created_at']))}${paidBy.isNotEmpty ? ' · $paidBy' : ''}',
                style: const TextStyle(color: Brand.muted, fontSize: 13)),
          ]),
        ),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(Fmt.money(asDouble(b['total'])), style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
          const SizedBox(height: 4),
          Pill(asStr(b['status_display']), color: status == 'paid' ? Brand.success : Brand.warning),
        ]),
      ]),
    );
  }
}

/// Receipt-style view of one bill with reprint.
class BillSheet extends StatefulWidget {
  const BillSheet({super.key, required this.bill});

  final Map<String, dynamic> bill;

  @override
  State<BillSheet> createState() => _BillSheetState();
}

class _BillSheetState extends State<BillSheet> {
  bool _printing = false;

  Future<void> _print() async {
    setState(() => _printing = true);
    try {
      final r = asMap(await context.read<ApiClient>().post('/bills/${widget.bill['id']}/print'));
      if (!mounted) return;
      await context.read<PrintService>().poll(); // prints straight away when this phone drives the printer
      if (!mounted) return;
      toast(context, asInt(r['queued']) > 0 ? 'Sent to the bill printer' : 'No printer connected - set one up under Printers',
          error: asInt(r['queued']) == 0);
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _printing = false);
    }
  }

  Future<void> _copy() async {
    try {
      final r = asMap(await context.read<ApiClient>().post('/bills/${widget.bill['id']}/print', {'to_printer': false}));
      await Clipboard.setData(ClipboardData(text: asStr(r['preview'])));
      if (mounted) toast(context, 'Bill copied - paste it into WhatsApp or SMS');
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final b = widget.bill;
    final rest = context.read<PosData>().restaurantName;
    Widget row(String l, String v, {bool bold = false}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(children: [
            Expanded(child: Text(l, style: TextStyle(fontWeight: bold ? FontWeight.w900 : FontWeight.w500, fontSize: bold ? 17 : 15))),
            Text(v, style: TextStyle(fontWeight: bold ? FontWeight.w900 : FontWeight.w700, fontSize: bold ? 17 : 15)),
          ]),
        );
    double n(String k) => asDouble(b[k]);
    final payments = listOf(b['payments']).map(asMap).where((p) => p['status'] == 'success').toList();
    return SheetFrame(
      title: 'Bill ${b['number']}',
      child: ListView(shrinkWrap: true, padding: const EdgeInsets.fromLTRB(20, 4, 20, 16), children: [
          Center(child: Text(rest, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 18))),
          Center(
            child: Text('${b['order_label']} · Order #${b['order_number']}',
                style: const TextStyle(color: Brand.muted, fontWeight: FontWeight.w600)),
          ),
          Center(
            child: Text(
              '${Fmt.isoDate(asDate(b['created_at']) ?? DateTime.now())} ${Fmt.time(asDate(b['created_at']))}'
              '${asStr(b['taken_by_name']).isNotEmpty ? ' · ${b['taken_by_name']}' : ''}',
              style: const TextStyle(color: Brand.muted, fontSize: 13),
            ),
          ),
          if (asStr(b['customer_name']).isNotEmpty || asStr(b['customer_phone']).isNotEmpty)
            Center(child: Text('Guest: ${b['customer_name']} ${b['customer_phone']}', style: const TextStyle(fontSize: 13))),
          const Divider(height: 24),
          for (final l in listOf(b['lines']).map(asMap)) row('${l['qty']} × ${l['name']}', Fmt.money(asDouble(l['amount']))),
          const Divider(height: 20),
          row('Subtotal', Fmt.money(n('subtotal'))),
          if (n('discount') > 0) row('Discount', '-${Fmt.money(n('discount'))}'),
          if (n('service_charge') > 0) row('Service charge', Fmt.money(n('service_charge'))),
          if (n('tax') > 0) row('GST', Fmt.money(n('tax'))),
          if (n('extra_charges') > 0) row('Delivery / packing', Fmt.money(n('extra_charges'))),
          if (n('round_off') != 0) row('Round off', Fmt.money(n('round_off'))),
          const Divider(height: 20),
          row('Total', Fmt.money(n('total')), bold: true),
          const SizedBox(height: 6),
          if (payments.isEmpty) const Text('Not paid yet', style: TextStyle(color: Brand.warning, fontWeight: FontWeight.w700)),
          for (final p in payments)
            row('${_methods[p['method']] ?? p['method']}${asStr(p['reference']).isNotEmpty ? ' (${p['reference']})' : ''}',
                Fmt.money(asDouble(p['amount']))),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(onPressed: _copy, icon: const Icon(Icons.copy_rounded), label: const Text('Copy')),
            ),
            const SizedBox(width: 10),
            Expanded(
              flex: 2,
              child: GradientButton(label: 'Print bill', icon: Icons.print_rounded, busy: _printing, onPressed: _print),
            ),
          ]),
      ]),
    );
  }
}
