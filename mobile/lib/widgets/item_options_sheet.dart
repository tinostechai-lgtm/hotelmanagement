import 'package:flutter/material.dart';

import '../brand/theme.dart';
import '../core/format.dart';
import '../models/cart.dart';
import '../models/menu.dart';
import 'common.dart';

/// Variant + add-on picker. Returns a configured [CartLine].
Future<CartLine?> pickItemOptions(BuildContext context, MenuItem item, {int? seat}) {
  return showSheet<CartLine>(context, (_) => _ItemOptionsSheet(item: item, seat: seat));
}

class _ItemOptionsSheet extends StatefulWidget {
  const _ItemOptionsSheet({required this.item, this.seat});

  final MenuItem item;
  final int? seat;

  @override
  State<_ItemOptionsSheet> createState() => _ItemOptionsSheetState();
}

class _ItemOptionsSheetState extends State<_ItemOptionsSheet> {
  Variant? _variant;
  final Map<int, Set<int>> _selected = {};
  final _notes = TextEditingController();
  double _qty = 1;

  @override
  void initState() {
    super.initState();
    if (widget.item.variants.isNotEmpty) _variant = widget.item.variants.first;
    for (final g in widget.item.addonGroups) {
      _selected[g.id] = <int>{};
    }
  }

  @override
  void dispose() {
    _notes.dispose();
    super.dispose();
  }

  List<Addon> get _addons => [
        for (final g in widget.item.addonGroups)
          for (final a in g.addons)
            if (_selected[g.id]!.contains(a.id)) a,
      ];

  String? get _validation {
    for (final g in widget.item.addonGroups) {
      final n = _selected[g.id]!.length;
      if (n < g.min) return 'Choose at least ${g.min} in ${g.name}';
    }
    return null;
  }

  void _toggle(AddonGroup g, Addon a) {
    setState(() {
      final set = _selected[g.id]!;
      if (set.contains(a.id)) {
        set.remove(a.id);
      } else {
        if (g.max == 1) set.clear();
        if (g.max > 1 && set.length >= g.max) return;
        set.add(a.id);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final line = CartLine(item: widget.item, variant: _variant, addons: _addons, qty: _qty, seat: widget.seat);
    final invalid = _validation;
    return SheetFrame(
      title: widget.item.name,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Flexible(
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.symmetric(horizontal: 20),
              children: [
                if (widget.item.description.isNotEmpty)
                  Text(widget.item.description, style: const TextStyle(color: Brand.muted)),
                if (widget.item.variants.isNotEmpty) ...[
                  const SectionTitle('Size / variant'),
                  Wrap(spacing: 8, runSpacing: 8, children: [
                    for (final v in widget.item.variants)
                      ChoiceChip(
                        label: Text('${v.name} · ${Fmt.money(v.price)}'),
                        selected: _variant?.id == v.id,
                        onSelected: (_) => setState(() => _variant = v),
                      ),
                  ]),
                ],
                for (final g in widget.item.addonGroups)
                  if (g.addons.isNotEmpty) ...[
                    SectionTitle(
                      g.name,
                      trailing: Text(
                        g.min > 0 ? 'Required${g.max > 0 ? ' · max ${g.max}' : ''}' : (g.max > 0 ? 'Up to ${g.max}' : 'Optional'),
                        style: const TextStyle(color: Brand.muted, fontSize: 12),
                      ),
                    ),
                    Wrap(spacing: 8, runSpacing: 8, children: [
                      for (final a in g.addons)
                        FilterChip(
                          label: Text(a.price > 0 ? '${a.name} +${Fmt.money(a.price)}' : a.name),
                          selected: _selected[g.id]!.contains(a.id),
                          onSelected: (_) => _toggle(g, a),
                        ),
                    ]),
                  ],
                const SectionTitle('Kitchen note'),
                TextField(
                  controller: _notes,
                  decoration: const InputDecoration(hintText: 'e.g. less spicy, no onion'),
                ),
                const SizedBox(height: 16),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
            child: Row(children: [
              IconButton.filledTonal(
                onPressed: _qty > 1 ? () => setState(() => _qty -= 1) : null,
                icon: const Icon(Icons.remove),
              ),
              SizedBox(
                width: 44,
                child: Text(Fmt.qty(_qty),
                    textAlign: TextAlign.center, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
              ),
              IconButton.filledTonal(onPressed: () => setState(() => _qty += 1), icon: const Icon(Icons.add)),
              const SizedBox(width: 16),
              Expanded(
                child: GradientButton(
                  label: invalid ?? 'Add · ${Fmt.money(line.total)}',
                  onPressed: invalid != null
                      ? null
                      : () {
                          line.notes = _notes.text.trim();
                          Navigator.pop(context, line);
                        },
                ),
              ),
            ]),
          ),
        ],
      ),
    );
  }
}
