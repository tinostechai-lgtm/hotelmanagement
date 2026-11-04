import '../core/json.dart';

class MenuCategory {
  MenuCategory({required this.id, required this.name, required this.items});

  factory MenuCategory.fromJson(Map<String, dynamic> j) {
    final id = asInt(j['id']);
    return MenuCategory(
      id: id,
      name: asStr(j['name']),
      items: (j['items'] is List ? j['items'] as List : const [])
          .map((e) => MenuItem.fromJson(asMap(e), categoryId: id))
          .toList(),
    );
  }

  final int id;
  final String name;
  final List<MenuItem> items;
}

class MenuItem {
  MenuItem({
    required this.id,
    required this.categoryId,
    required this.name,
    required this.description,
    required this.price,
    required this.diet,
    required this.shortCode,
    required this.barcode,
    required this.taxPercent,
    required this.available,
    required this.bestseller,
    required this.isWeighted,
    required this.variants,
    required this.addonGroups,
  });

  factory MenuItem.fromJson(Map<String, dynamic> j, {int categoryId = 0}) => MenuItem(
        id: asInt(j['id']),
        categoryId: categoryId,
        name: asStr(j['name']),
        description: asStr(j['description']),
        price: asDouble(j['dine_in_price'] ?? j['price']),
        diet: asStr(j['diet'], 'veg'),
        shortCode: asStr(j['short_code']),
        barcode: asStr(j['barcode']),
        taxPercent: asDouble(j['tax_percent']),
        available: asBool(j['available'], true),
        bestseller: asBool(j['bestseller']),
        isWeighted: asBool(j['is_weighted']),
        variants: (j['variants'] is List ? j['variants'] as List : const [])
            .map((e) => Variant.fromJson(asMap(e)))
            .toList(),
        addonGroups: (j['addon_groups'] is List ? j['addon_groups'] as List : const [])
            .map((e) => AddonGroup.fromJson(asMap(e)))
            .toList(),
      );

  final int id;
  final int categoryId;
  final String name;
  final String description;
  final double price;

  /// veg / non_veg / egg / vegan
  final String diet;
  final String shortCode;
  final String barcode;
  final double taxPercent;
  bool available;
  final bool bestseller;
  final bool isWeighted;
  final List<Variant> variants;
  final List<AddonGroup> addonGroups;

  bool get hasOptions => variants.isNotEmpty || addonGroups.any((g) => g.addons.isNotEmpty);

  bool matches(String q) {
    final s = q.trim().toLowerCase();
    if (s.isEmpty) return true;
    return name.toLowerCase().contains(s) ||
        shortCode.toLowerCase() == s ||
        shortCode.toLowerCase().startsWith(s) ||
        (barcode.isNotEmpty && barcode == q.trim());
  }
}

class Variant {
  Variant({required this.id, required this.name, required this.price});

  factory Variant.fromJson(Map<String, dynamic> j) =>
      Variant(id: asInt(j['id']), name: asStr(j['name']), price: asDouble(j['price']));

  final int id;
  final String name;
  final double price;
}

class AddonGroup {
  AddonGroup({required this.id, required this.name, required this.min, required this.max, required this.addons});

  factory AddonGroup.fromJson(Map<String, dynamic> j) => AddonGroup(
        id: asInt(j['id']),
        name: asStr(j['name']),
        min: asInt(j['min']),
        max: asInt(j['max']),
        addons: (j['addons'] is List ? j['addons'] as List : const []).map((e) => Addon.fromJson(asMap(e))).toList(),
      );

  final int id;
  final String name;
  final int min;

  /// 0 means unlimited.
  final int max;
  final List<Addon> addons;
}

class Addon {
  Addon({required this.id, required this.name, required this.price});

  factory Addon.fromJson(Map<String, dynamic> j) =>
      Addon(id: asInt(j['id']), name: asStr(j['name']), price: asDouble(j['price']));

  final int id;
  final String name;
  final double price;
}

class Station {
  Station(this.id, this.name);

  final int id;
  final String name;
}

class PaymentMethod {
  PaymentMethod(this.code, this.name);

  final String code;
  final String name;
}
