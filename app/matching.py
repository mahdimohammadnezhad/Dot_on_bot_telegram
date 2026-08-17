"""موتور تطبیق.

⚠️ از نسخه‌ی فعلی، تطبیق برای کاربران اجرا و نمایش داده نمی‌شود (هدف ربات جمع‌آوری
اطلاعات است، نه اشتراک‌گذاری آن). این ماژول فقط برای تحلیل‌های مدیریتی/آفلاین نگه داشته شده
و از مسیر بات فراخوانی نمی‌شود.
"""
from dataclasses import dataclass


@dataclass
class Offer:
    id: int
    delivery_period: str
    volume_kw: float
    min_price: float


@dataclass
class MatchPart:
    offer_id: int
    volume_kw: float
    price: float
    score: float


def match_request(request_period, request_volume, max_price, offers):
    candidates = [o for o in offers
                  if o.delivery_period == request_period and o.volume_kw > 0 and o.min_price <= max_price]
    candidates.sort(key=lambda x: x.min_price)

    remaining, result = request_volume, []
    for o in candidates:
        if remaining <= 0:
            break
        volume = min(remaining, o.volume_kw)
        score = max(0.0, min(100.0, (1 - o.min_price / max_price) * 1000 + 90))
        result.append(MatchPart(o.id, volume, o.min_price, score))
        remaining -= volume
    return result
