import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/format.dart';
import '../core/pos_data.dart';
import '../models/menu.dart';
import '../models/order.dart';
import '../widgets/common.dart';
import 'order_controller.dart';

/// Pushes pending items, then opens the payment sheet.
/// Resolves to true when a payment was recorded (or queued offline).
Future<bool?> showPaymentSheet(BuildContext context, OrderController c) async {
  final invalid = c.validateCustomer();
  if (invalid != null) {
    toast(context, invalid, error: true);
    return null;
  }
  var online = true;
  if (c.order == null || !c.cart.isEmpty) {
    try {
      online = await c.trySync();
    } catch (e) {
      if (context.mounted) toast(context, errorText(e), error: true);
      return null;
    }
  }
  if (!context.mounted) return null;
  if (!online && c.order != null) {
    toast(context, 'You are offline. Reconnect to take payment on this order.', error: true);
    return null;
  }
  return showSheet<bool>(
    context,
    (_) => ChangeNotifierProvider<OrderController>.value(value: c, child: _PaymentSheet(offline: !online)),
  );
}

class _Entry {
  _Entry(this.method, double amount) : amount = TextEditingController(text: _fmt(amount));

  String method;
  final TextEditingController amount;
  final TextEditingController tendered = TextEditingController();
  final TextEditingController reference = TextEditingController();

  double get value => double.tryParse(amount.text.trim()) ?? 0;
  double get tenderedValue => double.tryParse(tendered.text.trim()) ?? 0;

  static String _fmt(double v) => v <= 0 ? '' : (v == v.roundToDouble() ? v.toInt().toString() : v.toStringAsFixed(2));

  void dispose() {
    amount.dispose();
    tendered.dispose();
    reference.dispose();
  }
}

class _PaymentSheet extends StatefulWidget {
  const _PaymentSheet({required this.offline});

  final bool offline;

  @override
  State<_PaymentSheet> createState() => _PaymentSheetState();
}

class _PaymentSheetState extends State<_PaymentSheet> {
  final List<_Entry> _entries = [];
  int? _billId;
  bool _busy = false;

  OrderController get _c => Provider.of<OrderController>(context, listen: false);

  @override
  void initState() {
    super.initState();
    final bills = _payableBills(_c.order);
    if (bills.length > 1) _billId = bills.first.id;
    _entries.add(_Entry('cash', _due(_c)));
  }

  @override
  void dispose() {
    for (final e in _entries) {
      e.dispose();
    }
    super.dispose();
  }

  List<Bill> _payableBills(Order? o) => o == null ? const [] : o.activeBills.where((b) => b.status != 'paid').toList();

  double _due(OrderController c) {
    final o = c.order;
    if (widget.offline || o == null) return double.parse((c.cart.total + c.cart.estimatedTax).toStringAsFixed(2));
    if (_billId != null) {
      for (final b in o.activeBills) {
        if (b.id == _billId) return b.balance;
      }
    }
    return o.balance;
  }

  /// Controllers are disposed after the frame so the removed TextFields can
  /// detach from them first.
  void _disposeLater(_Entry e) => WidgetsBinding.instance.addPostFrameCallback((_) => e.dispose());

  void _resetAmounts() {
    for (final e in _entries) {
      _disposeLater(e);
    }
    _entries
      ..clear()
      ..add(_Entry('cash', _due(_c)));
  }

  List<PaymentMethod> _methods() {
    final all = Provider.of<PosData>(context, listen: false).paymentMethods;
    return all.where((m) => m.code != 'room' || _c.roomId != null).toList();
  }

  Future<void> _submit() async {
    final c = _c;
    final due = _due(c);
    final payments = <Map<String, dynamic>>[];
    var sum = 0.0;
    for (final e in _entries) {
      final amount = _entries.length == 1 && widget.offline ? due : e.value;
      if (amount <= 0) {
        toast(context, 'Enter an amount for ${Fmt.titleCase(e.method)}', error: true);
        return;
      }
      if (e.method == 'cash' && e.tenderedValue > 0 && e.tenderedValue < amount) {
        toast(context, 'Cash tendered is less than the amount', error: true);
        return;
      }
      sum += amount;
      payments.add({
        'method': e.method,
        // Offline: let the server charge the exact balance it computes.
        if (!widget.offline) 'amount': double.parse(amount.toStringAsFixed(2)),
        if (e.method == 'cash' && e.tenderedValue > 0) 'tendered': e.tenderedValue,
        if (e.reference.text.trim().isNotEmpty) 'reference': e.reference.text.trim(),
        if (_billId != null) 'bill': _billId,
      });
    }
    if (!widget.offline && sum > due + 0.01) {
      toast(context, 'Total ${Fmt.money(sum)} is more than the ${Fmt.money(due)} due', error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      if (widget.offline) {
        await c.payOffline(payments);
        if (mounted) Navigator.pop(context, true);
        return;
      }
      await c.pay(payments);
      if (!mounted) return;
      final o = c.order!;
      if (o.balance <= 0.01 || o.isPaid) {
        Navigator.pop(context, true);
      } else {
        final bills = _payableBills(o);
        setState(() {
          _billId = bills.length > 1 ? bills.first.id : null;
          _resetAmounts();
        });
        toast(context, 'Part payment recorded · ${Fmt.money(o.balance)} left');
      }
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _discount() async {
    final r = await showDialog<Map<String, dynamic>>(context: context, builder: (_) => const _DiscountDialog());
    if (r == null || !mounted) return;
    try {
      await _c.applyDiscount(
        percent: r['percent'] as double?,
        amount: r['amount'] as double?,
        coupon: r['coupon'] as String?,
        reason: (r['reason'] as String?) ?? '',
      );
      if (mounted) setState(_resetAmounts);
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  Future<void> _split() async {
    final r = await showDialog<Map<String, dynamic>>(context: context, builder: (_) => const _SplitDialog());
    if (r == null || !mounted) return;
    try {
      await _c.split(r['mode'] as String, parts: (r['parts'] as int?) ?? 2);
      if (!mounted) return;
      setState(() {
        final bills = _payableBills(_c.order);
        _billId = bills.isNotEmpty ? bills.first.id : null;
        _resetAmounts();
      });
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.watch<OrderController>();
    final o = c.order;
    final due = _due(c);
    final methods = _methods();
    final bills = _payableBills(o);
    final entered = _entries.fold<double>(0, (s, e) => s + e.value);
    final singleOffline = widget.offline;

    return SheetFrame(
      title: 'Payment',
      child: ListView(
        shrinkWrap: true,
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 20),
        children: [
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(gradient: Brand.inkGradient, borderRadius: BorderRadius.circular(18)),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(widget.offline ? 'Estimated due (offline)' : 'Amount due',
                      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text(Fmt.money(due), style: const TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.w900)),
                ]),
              ),
              if (o != null && o.discount > 0)
                Pill('−${Fmt.money(o.discount)} off', color: Brand.steam, filled: false),
            ]),
          ),
          if (widget.offline)
            const Padding(
              padding: EdgeInsets.only(top: 10),
              child: Text(
                'No connection. The bill and payment are saved on this device and sent to the server automatically; '
                'the exact total (with taxes) is calculated on sync.',
                style: TextStyle(color: Brand.warning, fontWeight: FontWeight.w600),
              ),
            ),
          if (!widget.offline && o != null) ...[
            const SizedBox(height: 12),
            Row(children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: c.busy ? null : _discount,
                  icon: const Icon(Icons.local_offer_outlined),
                  label: const Text('Discount'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: c.busy || o.paidAmount > 0 ? null : _split,
                  icon: const Icon(Icons.call_split),
                  label: const Text('Split bill'),
                ),
              ),
            ]),
          ],
          if (bills.length > 1) ...[
            const SectionTitle('Which bill?'),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final b in bills)
                ChoiceChip(
                  label: Text('${b.label.isEmpty ? b.number : b.label} · ${Fmt.money(b.balance)}'),
                  selected: _billId == b.id,
                  onSelected: (_) => setState(() {
                    _billId = b.id;
                    _resetAmounts();
                  }),
                ),
            ]),
          ],
          for (var i = 0; i < _entries.length; i++)
            _EntryEditor(
              key: ObjectKey(_entries[i]),
              entry: _entries[i],
              methods: methods,
              due: due,
              showAmount: !singleOffline,
              onRemove: _entries.length > 1
                  ? () => setState(() {
                        _disposeLater(_entries.removeAt(i));
                      })
                  : null,
              onChanged: () => setState(() {}),
            ),
          if (!singleOffline) ...[
            TextButton.icon(
              onPressed: () => setState(() {
                final left = due - entered;
                _entries.add(_Entry(_entries.last.method == 'cash' ? 'upi' : 'cash', left > 0 ? left : 0));
              }),
              icon: const Icon(Icons.add),
              label: const Text('Split across another method'),
            ),
            if (_entries.length > 1)
              Text(
                entered < due - 0.01
                    ? '${Fmt.money(due - entered)} still unallocated (will remain as balance)'
                    : 'Fully allocated',
                style: TextStyle(color: entered < due - 0.01 ? Brand.warning : Brand.success, fontWeight: FontWeight.w600),
              ),
          ],
          const SizedBox(height: 16),
          GradientButton(
            label: singleOffline ? 'Save bill & payment offline' : 'Collect ${Fmt.money(_entries.length == 1 ? _entries.first.value : entered)}',
            icon: Icons.check_circle_outline,
            busy: _busy,
            onPressed: _submit,
          ),
        ],
      ),
    );
  }
}

class _EntryEditor extends StatelessWidget {
  const _EntryEditor({
    super.key,
    required this.entry,
    required this.methods,
    required this.due,
    required this.showAmount,
    required this.onChanged,
    this.onRemove,
  });

  final _Entry entry;
  final List<PaymentMethod> methods;
  final double due;
  final bool showAmount;
  final VoidCallback onChanged;
  final VoidCallback? onRemove;

  List<double> _quickCash(double amount) {
    final out = <double>{amount};
    for (final step in const [50, 100, 500, 2000]) {
      final v = (amount / step).ceil() * step.toDouble();
      if (v > amount) out.add(v);
    }
    final list = out.toList()..sort();
    return list.take(4).toList();
  }

  @override
  Widget build(BuildContext context) {
    final amount = showAmount ? entry.value : due;
    final change = entry.tenderedValue - amount;
    return Container(
      margin: const EdgeInsets.only(top: 14),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(border: Border.all(color: Brand.line), borderRadius: BorderRadius.circular(16)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(
            child: Wrap(spacing: 6, runSpacing: 6, children: [
              for (final m in methods)
                ChoiceChip(
                  label: Text(m.name),
                  selected: entry.method == m.code,
                  onSelected: (_) {
                    entry.method = m.code;
                    onChanged();
                  },
                ),
            ]),
          ),
          if (onRemove != null) IconButton(onPressed: onRemove, icon: const Icon(Icons.close)),
        ]),
        if (showAmount) ...[
          const SizedBox(height: 10),
          TextField(
            controller: entry.amount,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            onChanged: (_) => onChanged(),
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
            decoration: const InputDecoration(labelText: 'Amount', prefixIcon: Icon(Icons.currency_rupee)),
          ),
        ],
        if (entry.method == 'cash') ...[
          const SizedBox(height: 10),
          TextField(
            controller: entry.tendered,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            onChanged: (_) => onChanged(),
            decoration: const InputDecoration(labelText: 'Cash received (optional)', prefixIcon: Icon(Icons.payments_outlined)),
          ),
          const SizedBox(height: 8),
          Wrap(spacing: 8, children: [
            for (final v in _quickCash(amount))
              ActionChip(
                label: Text(Fmt.money(v)),
                onPressed: () {
                  entry.tendered.text = v == v.roundToDouble() ? v.toInt().toString() : v.toStringAsFixed(2);
                  onChanged();
                },
              ),
          ]),
          if (entry.tenderedValue > 0)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                change >= 0 ? 'Return change: ${Fmt.money(change)}' : 'Short by ${Fmt.money(-change)}',
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                  color: change >= 0 ? Brand.success : Brand.danger,
                ),
              ),
            ),
        ] else if (entry.method == 'card' || entry.method == 'upi' || entry.method == 'wallet') ...[
          const SizedBox(height: 10),
          TextField(
            controller: entry.reference,
            decoration: const InputDecoration(labelText: 'Reference / last 4 digits (optional)', isDense: true),
          ),
        ] else if (entry.method == 'room')
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('Charge will be posted to the guest folio.', style: TextStyle(color: Brand.muted)),
          ),
      ]),
    );
  }
}

class _DiscountDialog extends StatefulWidget {
  const _DiscountDialog();

  @override
  State<_DiscountDialog> createState() => _DiscountDialogState();
}

class _DiscountDialogState extends State<_DiscountDialog> {
  String _mode = 'percent';
  final _value = TextEditingController();
  final _reason = TextEditingController();

  @override
  void dispose() {
    _value.dispose();
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Discount'),
      content: SizedBox(
        width: 380,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'percent', label: Text('%')),
              ButtonSegment(value: 'amount', label: Text('Amount')),
              ButtonSegment(value: 'coupon', label: Text('Coupon')),
            ],
            selected: {_mode},
            onSelectionChanged: (s) => setState(() => _mode = s.first),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _value,
            autofocus: true,
            textCapitalization: _mode == 'coupon' ? TextCapitalization.characters : TextCapitalization.none,
            keyboardType: _mode == 'coupon' ? TextInputType.text : const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              labelText: _mode == 'percent' ? 'Percent off' : (_mode == 'amount' ? 'Amount off' : 'Coupon code'),
            ),
          ),
          if (_mode != 'coupon') ...[
            const SizedBox(height: 10),
            Wrap(spacing: 8, children: [
              for (final p in _mode == 'percent' ? const [5, 10, 15, 20] : const [50, 100, 200])
                ActionChip(label: Text(_mode == 'percent' ? '$p%' : Fmt.money(p)), onPressed: () => _value.text = '$p'),
            ]),
            const SizedBox(height: 10),
            TextField(controller: _reason, decoration: const InputDecoration(labelText: 'Reason (optional)')),
          ],
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            final v = _value.text.trim();
            if (v.isEmpty) return;
            final number = double.tryParse(v);
            if (_mode != 'coupon' && number == null) return;
            Navigator.pop(context, <String, dynamic>{
              if (_mode == 'percent') 'percent': number,
              if (_mode == 'amount') 'amount': number,
              if (_mode == 'coupon') 'coupon': v.toUpperCase(),
              'reason': _reason.text.trim(),
            });
          },
          child: const Text('Apply'),
        ),
      ],
    );
  }
}

class _SplitDialog extends StatefulWidget {
  const _SplitDialog();

  @override
  State<_SplitDialog> createState() => _SplitDialogState();
}

class _SplitDialogState extends State<_SplitDialog> {
  String _mode = 'equal';
  int _parts = 2;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Split bill'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'equal', label: Text('Equal parts'), icon: Icon(Icons.pie_chart_outline)),
            ButtonSegment(value: 'seat', label: Text('By seat'), icon: Icon(Icons.event_seat_outlined)),
          ],
          selected: {_mode},
          onSelectionChanged: (s) => setState(() => _mode = s.first),
        ),
        const SizedBox(height: 16),
        if (_mode == 'equal')
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            IconButton.filledTonal(
              onPressed: _parts > 2 ? () => setState(() => _parts--) : null,
              icon: const Icon(Icons.remove),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 18),
              child: Text('$_parts ways', style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
            ),
            IconButton.filledTonal(
              onPressed: _parts < 20 ? () => setState(() => _parts++) : null,
              icon: const Icon(Icons.add),
            ),
          ])
        else
          const Text('One bill per seat number used when ordering. Items without a seat go on a shared bill.',
              style: TextStyle(color: Brand.muted)),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () => Navigator.pop(context, <String, dynamic>{'mode': _mode, 'parts': _parts}),
          child: const Text('Split'),
        ),
      ],
    );
  }
}
