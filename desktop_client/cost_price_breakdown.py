"""Read-only category and attachment details for the existing per-unit quotation."""
from quick_discount_rules import (
    money, money_sum, money_product, quick_discount_breakdown,
    quick_attachment_line_amount, quick_discount_category,
    ATTACHMENT_DISCOUNT_BASIS, quick_attachment_discounted_amount,
)


def quick_price_components(quote, attachments, discount, freight_fee=0, material_difference=0, thickness_surcharge=0):
    components, _ = quick_price_allocation(quote, attachments, discount, freight_fee,
                                           material_difference, thickness_surcharge)
    return components


def quick_price_allocation(quote, attachments, discount, freight_fee=0, material_difference=0, thickness_surcharge=0):
    """Return quote details and each attachment's share in input order."""
    rows = [row for row in attachments or [] if isinstance(row, dict)]
    source = quick_discount_breakdown(quote, rows, discount)
    eligible = {'柜体': source['base_price']}
    fixed = {}
    eligible_details, fixed_details = {}, {}
    attachment_totals = [0.0] * len(rows)
    for index, row in enumerate(rows):
        category = quick_discount_category(row)
        groups, details = (eligible, eligible_details) if category else (fixed, fixed_details)
        category = category or next((str(row[key]).strip() for key in
            ('category_level1', 'attachment_category', 'category', 'item_name', 'name')
            if row.get(key) and str(row[key]).strip()), '其他附件')
        amount = quick_attachment_line_amount(row)
        name = str(row.get('item_name') or row.get('name') or row.get('model_code') or '未命名附件').strip()
        groups[category] = money_sum((groups.get(category, 0), amount))
        details.setdefault(category, []).append((index, name or '未命名附件', amount))
    for category, amount in (('运费', max(0, float(freight_fee or 0))), ('材料差价', money_sum((material_difference, -thickness_surcharge))), ('料厚差价', thickness_surcharge)):
        if amount:
            fixed[category] = money_sum((fixed.get(category, 0), amount))
            if category in fixed_details:
                fixed_details[category].append((None, category, money(amount)))

    def explain(groups, details, factor):
        # Historical rows retain their cumulative allocation. Rows confirmed
        # in the unit-price editor use their own rounded unit times quantity.
        explained, cumulative, previous, total = [], 0, 0, 0
        for category, original in groups.items():
            entry = dict(category=category, original=money(original), discount=factor)
            if category in details:
                entry['details'] = []
                for index, name, detail_original in details[category]:
                    if index is not None and rows[index].get("quick_discount_basis") == ATTACHMENT_DISCOUNT_BASIS:
                        detail_amount = quick_attachment_discounted_amount(rows[index], factor)
                    else:
                        cumulative = money_sum((cumulative, detail_original))
                        current = money_product(cumulative, factor)
                        detail_amount = money_sum((current, -previous))
                        previous = current
                    entry['details'].append(dict(name=name, original=money(detail_original),
                                                 amount=detail_amount))
                    if index is not None:
                        attachment_totals[index] = detail_amount
                amount = money_sum(row['amount'] for row in entry['details'])
            else:
                cumulative = money_sum((cumulative, original))
                current = money_product(cumulative, factor)
                amount = money_sum((current, -previous))
                previous = current
            entry['amount'] = amount
            explained.append(entry)
            total = money_sum((total, amount))
        return dict(rows=explained, total=total)

    fixed = explain(fixed, fixed_details, 1)
    discounted = explain(eligible, eligible_details, source['discount'])
    components = dict(schema=1, basis='per_unit_set_v1', fixed=fixed, discounted=discounted,
                      total=money_sum((fixed['total'], discounted['total'])))
    return components, attachment_totals
