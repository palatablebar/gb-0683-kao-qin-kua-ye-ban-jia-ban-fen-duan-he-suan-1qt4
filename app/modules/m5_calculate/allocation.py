"""审批额度落段裁决：RATE_FIRST（高倍率优先）。

输入：
- priced：m5 费率切段后的计费片段（含 minutes/multiplier/rate/amount）；
- orders：approvals.parse 产出的有效审批单；
- issues：审批单解析异常（本模块补充 UNMATCHED 类异常）。

输出（就地增强并返回 state 所需结构）：
- 每个片段补 approved_minutes / unapproved_minutes / payable / withheld /
  allocation_policy / allocation_rank / order_ids；
- state['approval_ledger']：员工级逐项对应汇总；
- state['approval_issues']：解析异常 + 审批单无匹配加班的异常。

确定性：同倍率按片段起始时刻、再按段序打破平手；全部计算用 Decimal，分币守恒。
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

POLICY = 'RATE_FIRST'
CENT = Decimal('0.01')


def _pool(orders):
    """员工 -> [审批单]，保持单据原始顺序用于留痕。"""
    pool = defaultdict(list)
    for order in orders:
        pool[order['employee']].append(order)
    return pool


def allocate(priced, orders, issues=None):
    issues = list(issues or [])
    pools = _pool(orders)
    by_employee = defaultdict(list)
    for index, segment in enumerate(priced):
        by_employee[segment['employee']].append((index, segment))

    matched_employees = set(by_employee)
    for employee, group in pools.items():
        if employee not in matched_employees:
            for order in group:
                issues.append({'code': 'APPROVAL_UNMATCHED', 'order_id': order['order_id'],
                               'employee': employee, 'raw': order, 'source': order['source']})

    ledger = []
    for employee in sorted(matched_employees):
        group = by_employee[employee]
        quota = sum(order['approved_minutes'] for order in pools.get(employee, []))
        order_ids = [order['order_id'] for order in pools.get(employee, [])]
        remaining = quota
        # 裁决核心：倍率降序，同倍率按实际发生先后，再按段序保证确定性。
        ranked = sorted(group, key=lambda item: (-Decimal(item[1]['multiplier']),
                                                 item[1]['start'], item[0]))
        employee_actual = employee_approved = 0
        employee_payable = employee_withheld = Decimal('0')
        for rank, (index, segment) in enumerate(ranked, start=1):
            actual = int(segment['minutes'])
            approved = min(remaining, actual)
            remaining -= approved
            unapproved = actual - approved
            full = Decimal(segment['amount'])
            if actual:
                payable = (full * Decimal(approved) / Decimal(actual)).quantize(CENT, rounding=ROUND_HALF_UP)
            else:
                payable = Decimal('0.00')
            withheld = full - payable
            segment.update({
                'approved_minutes': approved,
                'unapproved_minutes': unapproved,
                'payable': str(payable),
                'withheld': str(withheld),
                'allocation_policy': POLICY,
                'allocation_rank': rank,
                'order_ids': list(order_ids),
            })
            employee_actual += actual
            employee_approved += approved
            employee_payable += payable
            employee_withheld += withheld
        ledger.append({
            'employee': employee,
            'actual_minutes': employee_actual,
            'approval_quota': quota,
            'approved_minutes': employee_approved,
            'unapproved_minutes': employee_actual - employee_approved,
            'unused_approval_minutes': max(0, quota - employee_approved),
            'order_ids': order_ids,
            'payable': str(employee_payable.quantize(CENT)),
            'withheld': str(employee_withheld.quantize(CENT)),
            'allocation_policy': POLICY,
        })
    return priced, ledger, issues
