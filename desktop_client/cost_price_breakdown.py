"""Read-only category and attachment details for the existing per-unit quotation."""
from quick_discount_rules import (
    money, money_sum, money_product, quick_discount_breakdown,
    quick_attachment_line_amount, quick_discount_category,
)


def quick_price_components(quote, attachments, discount, freight_fee=0, material_difference=0, thickness_surcharge=0):
    rows = [row for row in attachments or [] if isinstance(row, dict)]
    source = quick_discount_breakdown(quote, rows, discount)
    eligible = {'柜体': source['base_price']}
    fixed = {}
    eligible_details, fixed_details = {}, {}
    for row in rows:
        category = quick_discount_category(row)
        groups, details = (eligible, eligible_details) if category else (fixed, fixed_details)
        category = category or next((str(row[key]).strip() for key in
            ('category_level1', 'attachment_category', 'category', 'item_name', 'name')
            if row.get(key) and str(row[key]).strip()), '其他附件')
        amount = quick_attachment_line_amount(row)
        name = str(row.get('item_name') or row.get('name') or row.get('model_code') or '未命名附件').strip()
        groups[category] = money_sum((groups.get(category, 0), amount))
        details.setdefault(category, []).append((name or '未命名附件', amount))
    for category, amount in (('运费', max(0, float(freight_fee or 0))), ('材料差价', money_sum((material_difference, -thickness_surcharge))), ('料厚差价', thickness_surcharge)):
        if amount:
            fixed[category] = money_sum((fixed.get(category, 0), amount))
            if category in fixed_details:
                fixed_details[category].append((category, money(amount)))

    def explain(groups, details, factor):
        # Cumulative rounding allocates cents to categories while preserving
        # the existing whole-bucket discount and the formal quotation amount.
        explained, cumulative, previous = [], 0, 0
        for category, original in groups.items():
            detail_cumulative, detail_previous = cumulative, previous
            cumulative = money_sum((cumulative, original))
            current = money_product(cumulative, factor)
            amount = money_sum((current, -previous))
            entry = dict(category=category, original=money(original), discount=factor, amount=amount)
            if category in details:
                entry['details'] = []
                for name, detail_original in details[category]:
                    detail_cumulative = money_sum((detail_cumulative, detail_original))
                    detail_current = money_product(detail_cumulative, factor)
                    entry['details'].append(dict(name=name, original=money(detail_original),
                        amount=money_sum((detail_current, -detail_previous))))
                    detail_previous = detail_current
            explained.append(entry)
            previous = current
        return dict(rows=explained, total=money(previous))

    fixed = explain(fixed, fixed_details, 1)
    discounted = explain(eligible, eligible_details, source['discount'])
    return dict(schema=1, basis='per_unit_set_v1', fixed=fixed, discounted=discounted,
                total=money_sum((fixed['total'], discounted['total'])))
