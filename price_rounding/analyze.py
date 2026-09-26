import json
import statistics

from pathlib import Path
with open(Path(__file__).resolve().parent / 'final_rounding_ranges.json', encoding='utf-8') as f:
    data = json.load(f)

res = []
for k, v in data.items():
    prices = v['all_real_prices']
    count = len(prices)
    if count > 0:
        mean_val = statistics.mean(prices)
        med_val = statistics.median(prices)
        res.append((float(k), mean_val, med_val, count))

res.sort()

print("EXPECTED_EARNINGS = {")
for k, mean_val, med_val, count in res:
    if count >= 10:
        # Выводим только те, где n >= 10, чтобы статистика была достоверной
        print(f"    {int(k)}: {mean_val:.2f},   # n={count} (медиана была {med_val:.2f})")
print("}")
print("\n# FALLBACK (для редких сумм, где n < 10):")
print("def estimate_review_earnings(review_price: float) -> float:")
print("    price = int(review_price)")
print("    if price in EXPECTED_EARNINGS:")
print("        return EXPECTED_EARNINGS[price]")
print("    return price * 0.85  # Универсальный вычет 15% комиссии")
