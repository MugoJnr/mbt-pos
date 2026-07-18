"""
Pure-Python category → icon suggestions (no Qt).
Safe to import from api_client / backend schema bootstrap.
"""
from __future__ import annotations

_NAME_ICON_HINTS = [
    (('grocery', 'supermarket', 'food', 'provision'), 'food/flour-unga'),
    (('produce', 'vegetable', 'fruit', 'meat', 'fresh'), 'food/vegetables'),
    (('pharma', 'chemist', 'medicine', 'drug'), 'pharmacy/tablets-pills'),
    (('household', 'cleaning', 'detergent', 'soap'), 'home/soap-detergent'),
    (('beauty', 'cosmetic', 'personal'), 'beauty/lipstick-makeup'),
    (('cloth', 'apparel', 'fashion', 'wear'), 'clothing/t-shirt'),
    (('electronic', 'phone', 'mobile', 'gadget'), 'electronics/mobile-phone'),
    (('hardware', 'build', 'tool'), 'hardware/hammer'),
    (('agro', 'vet', 'feed', 'farm', 'seed'), 'agriculture/seeds'),
    (('restaurant', 'cafe', 'kitchen', 'food service'), 'restaurant/burgers'),
    (('stationer', 'school', 'office', 'book'), 'office/books-textbooks'),
    (('auto', 'spare', 'workshop', 'motor'), 'automotive/engine-parts'),
    (('toy', 'game', 'entertainment'), 'toys/video-games'),
    (('furniture', 'home'), 'furniture/sofa-furniture'),
    (('cookware', 'kitchenware', 'utensil'), 'home/frying-pan'),
    (('pet',), 'pets/dog-food-care'),
    (('energy', 'fuel', 'gas', 'solar', 'utility'), 'logistics/kerosene-paraffin'),
    (('drink', 'beverage', 'soda', 'juice'), 'drinks/soda-drink'),
    (('bakery', 'bread', 'pastry'), 'bakery/bread'),
    (('general', 'misc', 'other', 'default'), 'generic/general-product'),
]

_NAME_COLOR_HINTS = [
    (('pharma', 'chemist'), '#3B82F6'),
    (('food', 'grocery', 'produce'), '#22C55E'),
    (('drink', 'beverage'), '#06B6D4'),
    (('electronic',), '#8B5CF6'),
    (('cloth',), '#EC4899'),
    (('beauty',), '#F472B6'),
    (('hardware', 'auto'), '#64748B'),
    (('agro', 'farm', 'seed'), '#16A34A'),
    (('restaurant',), '#F59E0B'),
]


def suggest_visual_for_category_name(name: str) -> dict:
    """Return {visual_type, icon_name, accent_color} for seeding."""
    low = (name or '').strip().lower()
    icon = 'generic/general-product'
    color = '#3B82F6'
    for keys, iid in _NAME_ICON_HINTS:
        if any(k in low for k in keys):
            icon = iid
            break
    for keys, col in _NAME_COLOR_HINTS:
        if any(k in low for k in keys):
            color = col
            break
    return {
        'visual_type': 'icon',
        'icon_name': icon,
        'image_path': None,
        'accent_color': color,
    }
