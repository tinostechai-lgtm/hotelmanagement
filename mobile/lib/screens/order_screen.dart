import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/format.dart';
import '../core/offline_queue.dart';
import '../core/pos_data.dart';
import '../models/cart.dart';
import '../models/menu.dart';
import '../models/order.dart';
import '../widgets/common.dart';
import '../widgets/item_options_sheet.dart';
import '../widgets/offline_banner.dart';
import '../widgets/scanner_sheet.dart';
import 'order_controller.dart';
import 'payment_sheet.dart';

export 'order_controller.dart' show OrderTarget;

class OrderScreen extends StatelessWidget {
  const OrderScreen({super.key, required this.target});

  final OrderTarget target;

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<OrderController>(
      create: (ctx) => OrderController(
        api: ctx.read<ApiClient>(),
        queue: ctx.read<OfflineQueue>(),
        target: target,
      )..load(),
      child: const _OrderView(),
    );
  }
}

class _OrderView extends StatelessWidget {
  const _OrderView();

  @override
  Widget build(BuildContext context) {
    final c = context.watch<OrderController>();
    final wide = isWide(context);
    return Scaffold(
      appBar: AppBar(
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(c.title, overflow: TextOverflow.ellipsis),
          Text(orderTypeLabels[c.orderType] ?? c.orderType,
              style: const TextStyle(fontSize: 13, color: Brand.steam, fontWeight: FontWeight.w600)),
        ]),
        actions: [
          IconButton(
            tooltip: 'Scan barcode',
            icon: const Icon(Icons.qr_code_scanner),
            onPressed: () => _scan(context),
          ),
          if (c.order != null)
            IconButton(tooltip: 'Refresh', icon: const Icon(Icons.refresh), onPressed: c.refresh),
        ],
      ),
      body: Column(children: [
        const OfflineBanner(),
        if (c.loading) const LinearProgressIndicator(),
        if (c.loadError != null)
          MaterialBanner(
            content: Text(c.loadError!),
            actions: [TextButton(onPressed: c.load, child: const Text('Retry'))],
          ),
        Expanded(
          child: wide
              ? Row(children: [
                  const Expanded(child: MenuPanel()),
                  Container(
                    width: 410,
                    decoration: const BoxDecoration(color: Colors.white, border: Border(left: BorderSide(color: Brand.line))),
                    child: const CartPanel(),
                  ),
                ])
              : const MenuPanel(),
        ),
      ]),
      bottomNavigationBar: wide ? null : const _CartBar(),
    );
  }

  Future<void> _scan(BuildContext context) async {
    final code = await scanBarcode(context);
    if (code == null || !context.mounted) return;
    final item = context.read<PosData>().findByCode(code);
    if (item == null) {
      toast(context, 'No item with code $code', error: true);
      return;
    }
    await addItemToCart(context, item);
  }
}

Future<void> addItemToCart(BuildContext context, MenuItem item) async {
  final c = context.read<OrderController>();
  if (!item.available) {
    toast(context, '${item.name} is marked sold out. Long-press to make it available.', error: true);
    return;
  }
  HapticFeedback.selectionClick();
  if (item.hasOptions) {
    final line = await pickItemOptions(context, item, seat: c.seat);
    if (line != null) c.cart.add(line);
  } else {
    c.cart.add(CartLine(item: item, seat: c.seat));
  }
}

/// Mobile bottom bar summarising the cart; opens the full cart sheet.
class _CartBar extends StatelessWidget {
  const _CartBar();

  @override
  Widget build(BuildContext context) {
    final c = context.watch<OrderController>();
    final sent = c.order?.total ?? 0;
    final count = c.cart.count + (c.order?.liveItems.length ?? 0);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
        child: GradientButton(
          icon: Icons.shopping_basket_outlined,
          label: count == 0
              ? 'Cart is empty'
              : 'View order · ${c.cart.count > 0 ? '${c.cart.count} new · ' : ''}${Fmt.money(sent + c.cart.total)}',
          onPressed: () => showSheet<void>(
            context,
            (_) => ChangeNotifierProvider<OrderController>.value(
              value: c,
              child: SizedBox(height: MediaQuery.sizeOf(context).height * 0.88, child: const CartPanel(inSheet: true)),
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Menu
// ---------------------------------------------------------------------------

class MenuPanel extends StatefulWidget {
  const MenuPanel({super.key});

  @override
  State<MenuPanel> createState() => _MenuPanelState();
}

class _MenuPanelState extends State<MenuPanel> {
  final _search = TextEditingController();
  int? _category;

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _toggleAvailability(MenuItem item) async {
    final api = context.read<ApiClient>();
    final data = context.read<PosData>();
    final makeAvailable = !item.available;
    final ok = await confirm(
      context,
      makeAvailable ? 'Back in stock?' : 'Mark sold out?',
      makeAvailable ? '${item.name} will be orderable again everywhere.' : '${item.name} will be hidden from POS, QR and online menus.',
      ok: makeAvailable ? 'Available' : 'Sold out',
    );
    if (!ok) return;
    try {
      final res = await api.post('/items/${item.id}/toggle', {'available': makeAvailable});
      data.setItemAvailable(item.id, res is Map && res['is_available'] is bool ? res['is_available'] as bool : makeAvailable);
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final data = context.watch<PosData>();
    final c = context.watch<OrderController>();
    final q = _search.text;
    final items = <MenuItem>[
      for (final cat in data.categories)
        if (_category == null || _category == cat.id || q.isNotEmpty)
          for (final i in cat.items)
            if (i.matches(q)) i,
    ];
    final inCart = <int, double>{};
    for (final l in c.cart.lines) {
      inCart[l.item.id] = (inCart[l.item.id] ?? 0) + l.qty;
    }

    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
        child: TextField(
          controller: _search,
          onChanged: (_) => setState(() {}),
          textInputAction: TextInputAction.search,
          onSubmitted: (v) {
            final hit = data.findByCode(v);
            if (hit != null) {
              addItemToCart(context, hit);
              _search.clear();
              setState(() {});
            }
          },
          decoration: InputDecoration(
            hintText: 'Search name or short code',
            prefixIcon: const Icon(Icons.search),
            suffixIcon: q.isEmpty
                ? null
                : IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () => setState(_search.clear),
                  ),
          ),
        ),
      ),
      SizedBox(
        height: 52,
        child: ListView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          children: [
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(label: const Text('All'), selected: _category == null, onSelected: (_) => setState(() => _category = null)),
            ),
            for (final cat in data.categories)
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text(cat.name),
                  selected: _category == cat.id,
                  onSelected: (_) => setState(() => _category = cat.id),
                ),
              ),
          ],
        ),
      ),
      Expanded(
        child: items.isEmpty
            ? EmptyState(
                icon: Icons.restaurant_menu,
                title: data.categories.isEmpty ? 'Menu not loaded' : 'No matching items',
                message: data.categories.isEmpty ? 'Pull to refresh on the home screen once online.' : null,
              )
            : GridView.builder(
                padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                  maxCrossAxisExtent: 210,
                  mainAxisExtent: 138,
                  mainAxisSpacing: 10,
                  crossAxisSpacing: 10,
                ),
                itemCount: items.length,
                itemBuilder: (_, i) => _ItemTile(
                  item: items[i],
                  qty: inCart[items[i].id] ?? 0,
                  onTap: () => addItemToCart(context, items[i]),
                  onLongPress: () => _toggleAvailability(items[i]),
                ),
              ),
      ),
    ]);
  }
}

class _ItemTile extends StatelessWidget {
  const _ItemTile({required this.item, required this.qty, required this.onTap, required this.onLongPress});

  final MenuItem item;
  final double qty;
  final VoidCallback onTap;
  final VoidCallback onLongPress;

  static const _tints = [
    Color(0xFFFFEDE3), Color(0xFFEDE9FE), Color(0xFFDCFCE7), Color(0xFFE0F2FE), Color(0xFFFEF3C7), Color(0xFFFCE7F3),
  ];
  static const _inks = [
    Color(0xFFC2410C), Color(0xFF6D28D9), Color(0xFF15803D), Color(0xFF0369A1), Color(0xFFB45309), Color(0xFFBE185D),
  ];

  @override
  Widget build(BuildContext context) {
    final soldOut = !item.available;
    final selected = qty > 0;
    final k = item.name.isEmpty ? 0 : item.name.codeUnitAt(0) % _tints.length;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      decoration: BoxDecoration(
        color: soldOut ? const Color(0xFFF1F1F4) : Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: selected ? Brand.orangeDeep : Colors.transparent, width: 2),
        boxShadow: soldOut ? null : Brand.shadow,
      ),
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(18),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          onLongPress: onLongPress,
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Container(
                  width: 38,
                  height: 38,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(color: _tints[k], borderRadius: BorderRadius.circular(12)),
                  child: Text(item.name.isEmpty ? '?' : item.name[0].toUpperCase(),
                      style: TextStyle(color: _inks[k], fontWeight: FontWeight.w900, fontSize: 18)),
                ),
                const Spacer(),
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Row(mainAxisSize: MainAxisSize.min, children: [
                    if (item.bestseller) const Icon(Icons.star_rounded, size: 16, color: Brand.warning),
                    const SizedBox(width: 4),
                    DietDot(item.diet),
                  ]),
                  if (item.shortCode.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(item.shortCode, style: const TextStyle(fontSize: 11, color: Brand.muted, fontWeight: FontWeight.w700)),
                  ],
                ]),
              ]),
              const SizedBox(height: 8),
              Expanded(
                child: Text(
                  item.name,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 15,
                    height: 1.2,
                    color: soldOut ? Brand.muted : Brand.ink,
                    decoration: soldOut ? TextDecoration.lineThrough : null,
                  ),
                ),
              ),
              Row(children: [
                Text(Fmt.money(item.variants.isNotEmpty ? item.variants.first.price : item.price),
                    style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15, color: Brand.ink)),
                if (item.hasOptions) const Text(' +', style: TextStyle(color: Brand.muted, fontWeight: FontWeight.w700)),
                const Spacer(),
                if (soldOut)
                  const Pill('SOLD OUT', color: Brand.danger)
                else if (selected)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                    decoration: BoxDecoration(gradient: Brand.gradient, borderRadius: BorderRadius.circular(99)),
                    child: Text('×${Fmt.qty(qty)}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 13)),
                  )
                else
                  Container(
                    width: 28,
                    height: 28,
                    decoration: BoxDecoration(color: Brand.orangeDeep.withOpacity(0.1), shape: BoxShape.circle),
                    child: const Icon(Icons.add_rounded, size: 18, color: Brand.orangeDeep),
                  ),
              ]),
            ]),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Cart / order panel
// ---------------------------------------------------------------------------

class CartPanel extends StatelessWidget {
  const CartPanel({super.key, this.inSheet = false});

  final bool inSheet;

  Future<void> _do(BuildContext context, Future<String> Function() action, {bool popIfOffline = true}) async {
    final c = context.read<OrderController>();
    final nav = Navigator.of(context);
    try {
      final msg = await action();
      if (!context.mounted) return;
      toast(context, msg);
      if (c.savedOffline && popIfOffline) {
        if (inSheet) nav.pop();
        nav.maybePop();
      }
    } catch (e) {
      if (context.mounted) toast(context, errorText(e), error: true);
    }
  }

  Future<void> _pay(BuildContext context) async {
    final c = context.read<OrderController>();
    final nav = Navigator.of(context);
    final paid = await showPaymentSheet(context, c);
    if (paid == true && context.mounted) {
      final o = c.order;
      if (c.savedOffline || (o != null && o.isClosed)) {
        toast(context, c.savedOffline ? 'Saved offline with payment – will sync automatically' : 'Payment received · order closed');
        if (inSheet) nav.pop();
        nav.maybePop();
      } else {
        toast(context, 'Payment recorded');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.watch<OrderController>();
    final o = c.order;
    final children = <Widget>[
      if (o != null)
        Row(children: [
          Pill(o.statusDisplay, color: o.isClosed ? Brand.muted : Brand.info),
          const SizedBox(width: 8),
          if (o.isPaid) const Pill('PAID', color: Brand.success),
          const Spacer(),
          if (o.activeBills.isNotEmpty)
            TextButton.icon(
              onPressed: () => _do(context, () async {
                await c.reprintBill();
                return 'Bill sent to printer';
              }),
              icon: const Icon(Icons.print_outlined),
              label: const Text('Reprint'),
            ),
        ]),
      if (c.needsCustomer) _CustomerFields(controller: c),
      if (c.isDineIn && (o == null || !o.isClosed)) _SeatPicker(controller: c),
      if (o != null && o.liveItems.isNotEmpty) ...[
        const SectionTitle('Sent to kitchen'),
        for (final l in o.liveItems) _SentLine(line: l, controller: c),
      ],
      if (!c.cart.isEmpty) ...[
        SectionTitle('New items', trailing: TextButton(onPressed: c.cart.clear, child: const Text('Clear'))),
        for (final l in c.cart.lines) _CartLineTile(line: l, cart: c.cart),
      ],
      if (o == null && c.cart.isEmpty)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 40),
          child: EmptyState(icon: Icons.touch_app_outlined, title: 'Tap items to add them'),
        ),
      if (o != null && !o.isClosed && o.nextStatuses.isNotEmpty) _StatusActions(controller: c),
    ];

    return Column(children: [
      if (inSheet)
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 12, 0),
          child: Row(children: [
            Expanded(child: Text(c.title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800))),
            IconButton(onPressed: () => Navigator.pop(context), icon: const Icon(Icons.close)),
          ]),
        ),
      Expanded(child: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 8), children: children)),
      _Totals(controller: c),
      if (o == null || !o.isClosed)
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
          child: Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: c.busy ? null : () => _do(context, c.sendKot),
                icon: const Icon(Icons.soup_kitchen_outlined),
                label: const Text('KOT'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: c.busy ? null : () => _do(context, c.generateBill),
                icon: const Icon(Icons.receipt_outlined),
                label: const Text('Bill'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: GradientButton(
                label: 'Pay',
                icon: Icons.payments_outlined,
                height: 52,
                busy: c.busy,
                onPressed: (o == null && c.cart.isEmpty) || (o != null && o.isPaid && c.cart.isEmpty) ? null : () => _pay(context),
              ),
            ),
          ]),
        ),
    ]);
  }
}

class _CustomerFields extends StatelessWidget {
  const _CustomerFields({required this.controller});

  final OrderController controller;

  @override
  Widget build(BuildContext context) {
    final delivery = controller.orderType == 'delivery';
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(children: [
        Row(children: [
          Expanded(
            child: TextField(
              controller: controller.customerPhone,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(labelText: 'Customer phone', prefixIcon: Icon(Icons.phone), isDense: true),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: controller.customerName,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(labelText: 'Name', isDense: true),
            ),
          ),
        ]),
        if (delivery) ...[
          const SizedBox(height: 8),
          TextField(
            controller: controller.deliveryAddress,
            minLines: 1,
            maxLines: 3,
            decoration: const InputDecoration(labelText: 'Delivery address', prefixIcon: Icon(Icons.location_on_outlined), isDense: true),
          ),
        ],
      ]),
    );
  }
}

class _SeatPicker extends StatelessWidget {
  const _SeatPicker({required this.controller});

  final OrderController controller;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 48,
      child: ListView(scrollDirection: Axis.horizontal, children: [
        const Center(child: Text('Seat  ', style: TextStyle(fontWeight: FontWeight.w700, color: Brand.muted))),
        Padding(
          padding: const EdgeInsets.only(right: 6),
          child: ChoiceChip(
            label: const Text('Shared'),
            selected: controller.seat == null,
            onSelected: (_) => controller.setSeat(null),
          ),
        ),
        for (var s = 1; s <= 8; s++)
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: ChoiceChip(
              label: Text('$s'),
              selected: controller.seat == s,
              onSelected: (_) => controller.setSeat(s),
            ),
          ),
      ]),
    );
  }
}

class _SentLine extends StatelessWidget {
  const _SentLine({required this.line, required this.controller});

  final OrderLine line;
  final OrderController controller;

  Future<void> _void(BuildContext context) async {
    final reason = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Void ${line.displayName}?'),
        content: TextField(controller: reason, decoration: const InputDecoration(labelText: 'Reason')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Void')),
        ],
      ),
    );
    final text = reason.text.trim();
    reason.dispose();
    if (ok != true) return;
    try {
      await controller.voidLine(line, text);
    } catch (e) {
      if (context.mounted) toast(context, errorText(e), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        SizedBox(
          width: 34,
          child: Text('${Fmt.qty(line.quantity)}×', style: const TextStyle(fontWeight: FontWeight.w800)),
        ),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(line.displayName, style: const TextStyle(fontWeight: FontWeight.w600)),
            Text(
              [Fmt.titleCase(line.status), if (line.seat != null) 'Seat ${line.seat}', if (line.notes.isNotEmpty) line.notes]
                  .join(' · '),
              style: const TextStyle(fontSize: 12, color: Brand.muted),
            ),
          ]),
        ),
        Text(Fmt.money(line.lineTotal), style: const TextStyle(fontWeight: FontWeight.w700)),
        if (!(controller.order?.isClosed ?? true))
          IconButton(
            tooltip: 'Void',
            visualDensity: VisualDensity.compact,
            icon: const Icon(Icons.remove_circle_outline, color: Brand.danger),
            onPressed: () => _void(context),
          ),
      ]),
    );
  }
}

class _CartLineTile extends StatelessWidget {
  const _CartLineTile({required this.line, required this.cart});

  final CartLine line;
  final Cart cart;

  Future<void> _editNote(BuildContext context) async {
    final ctl = TextEditingController(text: line.notes);
    final r = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Kitchen note'),
        content: TextField(controller: ctl, autofocus: true, decoration: const InputDecoration(hintText: 'e.g. extra spicy')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, ctl.text.trim()), child: const Text('Save')),
        ],
      ),
    );
    ctl.dispose();
    if (r != null) cart.setNotes(line, r);
  }

  @override
  Widget build(BuildContext context) {
    final sub = [
      if (line.subtitle.isNotEmpty) line.subtitle,
      if (line.seat != null) 'Seat ${line.seat}',
      if (line.notes.isNotEmpty) '“${line.notes}”',
    ].join(' · ');
    return InkWell(
      onTap: () => _editNote(context),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(children: [
          DietDot(line.item.diet, size: 12),
          const SizedBox(width: 8),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(line.title, style: const TextStyle(fontWeight: FontWeight.w700)),
              Text(sub.isEmpty ? 'Tap to add a note' : sub, style: const TextStyle(fontSize: 12, color: Brand.muted)),
            ]),
          ),
          _Stepper(
            qty: line.qty,
            onMinus: () => cart.decrement(line),
            onPlus: () => cart.increment(line),
          ),
          SizedBox(
            width: 72,
            child: Text(Fmt.money(line.total), textAlign: TextAlign.right, style: const TextStyle(fontWeight: FontWeight.w800)),
          ),
        ]),
      ),
    );
  }
}

class _Stepper extends StatelessWidget {
  const _Stepper({required this.qty, required this.onMinus, required this.onPlus});

  final double qty;
  final VoidCallback onMinus;
  final VoidCallback onPlus;

  @override
  Widget build(BuildContext context) {
    Widget btn(IconData icon, VoidCallback onTap) => InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(10),
          child: SizedBox(width: 40, height: 40, child: Icon(icon, size: 20, color: Brand.orangeDeep)),
        );
    return Container(
      decoration: BoxDecoration(
        border: Border.all(color: Brand.line),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        btn(Icons.remove, onMinus),
        SizedBox(
          width: 28,
          child: Text(Fmt.qty(qty), textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
        ),
        btn(Icons.add, onPlus),
      ]),
    );
  }
}

class _StatusActions extends StatelessWidget {
  const _StatusActions({required this.controller});

  final OrderController controller;

  @override
  Widget build(BuildContext context) {
    final o = controller.order!;
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Wrap(spacing: 8, runSpacing: 8, children: [
        for (final s in o.nextStatuses)
          ActionChip(
            avatar: Icon(s == 'cancelled' ? Icons.cancel_outlined : Icons.arrow_forward, size: 18,
                color: s == 'cancelled' ? Brand.danger : Brand.ink),
            label: Text(s == 'completed' ? 'Complete order' : Fmt.titleCase(s)),
            onPressed: () async {
              if (s == 'cancelled' &&
                  !await confirm(context, 'Cancel order?', 'This cancels #${o.number} and frees the table.', ok: 'Cancel order')) {
                return;
              }
              try {
                await controller.setStatus(s, reason: s == 'cancelled' ? 'Cancelled from app' : '');
              } catch (e) {
                if (context.mounted) toast(context, errorText(e), error: true);
              }
            },
          ),
      ]),
    );
  }
}

class _Totals extends StatelessWidget {
  const _Totals({required this.controller});

  final OrderController controller;

  @override
  Widget build(BuildContext context) {
    final o = controller.order;
    final cart = controller.cart;
    Widget row(String label, double v, {bool bold = false, Color? color}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(children: [
            Text(label, style: TextStyle(color: color ?? Brand.muted, fontWeight: bold ? FontWeight.w800 : FontWeight.w500)),
            const Spacer(),
            Text(Fmt.money(v),
                style: TextStyle(
                  color: color ?? Brand.ink,
                  fontWeight: bold ? FontWeight.w900 : FontWeight.w600,
                  fontSize: bold ? 18 : 14,
                )),
          ]),
        );
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 6),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: Brand.line))),
      child: Column(children: [
        if (o != null) ...[
          row('Subtotal', o.subtotal),
          if (o.discount > 0) row('Discount', -o.discount, color: Brand.success),
          if (o.serviceCharge > 0) row('Service charge', o.serviceCharge),
          row('Tax', o.tax),
          if (o.extraCharges > 0) row('Delivery / packing / tip', o.extraCharges),
          row('Total', o.total, bold: true),
          if (o.paidAmount > 0) row('Paid', o.paidAmount, color: Brand.success),
          if (o.paidAmount > 0 && o.balance > 0) row('Balance', o.balance, bold: true, color: Brand.orangeDeep),
        ],
        if (!cart.isEmpty) row('New items (est. incl. tax)', cart.total + cart.estimatedTax, bold: o == null),
      ]),
    );
  }
}
