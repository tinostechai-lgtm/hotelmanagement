import '../core/json.dart';

class Membership {
  Membership({
    required this.restaurantId,
    required this.restaurant,
    required this.slug,
    required this.businessType,
    required this.role,
    required this.permissions,
    required this.features,
    this.plan,
    this.brandColor,
  });

  factory Membership.fromJson(Map<String, dynamic> j) => Membership(
        restaurantId: asInt(j['restaurant_id']),
        restaurant: asStr(j['restaurant']),
        slug: asStr(j['slug']),
        businessType: asStr(j['business_type']),
        role: asStr(j['role']),
        permissions: asStringList(j['permissions']),
        features: asStringList(j['features']),
        plan: j['plan']?.toString(),
        brandColor: j['brand_color']?.toString(),
      );

  final int restaurantId;
  final String restaurant;
  final String slug;
  final String businessType;
  final String role;
  final List<String> permissions;
  final List<String> features;
  final String? plan;
  final String? brandColor;
}
