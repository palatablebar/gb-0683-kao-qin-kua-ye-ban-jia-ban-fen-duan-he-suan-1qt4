from decimal import Decimal


def _check(code, label, ok, detail=''):
    return {'code': code, 'label': label, 'ok': bool(ok), 'detail': detail}


def approval_checks(state):
    """审批落段的守恒校验：分钟守恒、额度不超额、分币守恒、应付独立求和一致。"""
    checks = []
    calculations = state.get('calculations', [])
    ledger = state.get('approval_ledger', [])
    business = state.get('business', {})

    # 1) 逐片段分钟守恒：实际 = 已批 + 未批，且已批不超过实际。
    minute_ok = all(r['minutes'] == r.get('approved_minutes', 0) + r.get('unapproved_minutes', 0)
                    and 0 <= r.get('approved_minutes', 0) <= r['minutes'] for r in calculations)
    checks.append(_check('APPROVAL_MINUTES', '片段分钟守恒（实际=已批+未批）', minute_ok))

    # 2) 员工汇总与片段独立求和一致，且已批 = min(额度, 实际)。
    seg_approved = sum(r.get('approved_minutes', 0) for r in calculations)
    seg_unapproved = sum(r.get('unapproved_minutes', 0) for r in calculations)
    ledger_approved = sum(r['approved_minutes'] for r in ledger)
    quota_ok = all(r['approved_minutes'] == min(r['approval_quota'], r['actual_minutes'])
                   and r['approved_minutes'] + r['unapproved_minutes'] == r['actual_minutes']
                   and r['approved_minutes'] + r['unused_approval_minutes'] == r['approval_quota']
                   for r in ledger)
    checks.append(_check('APPROVAL_LEDGER', '员工额度守恒（已批=min(额度,实际)）',
                         quota_ok and seg_approved == ledger_approved
                         and seg_unapproved == sum(r['unapproved_minutes'] for r in ledger)))

    # 3) 分币守恒：逐片段 全额 = 应付 + 不付。
    cash_ok = all(Decimal(r['amount']) == Decimal(r['payable']) + Decimal(r['withheld'])
                  for r in calculations)
    checks.append(_check('PAYABLE_SPLIT', '分币守恒（金额=应付+不付）', cash_ok))

    # 4) 应付独立求和：片段求和 == 台账求和 == 业务汇总。
    row_payable = sum((Decimal(r['payable']) for r in calculations), Decimal('0'))
    ledger_payable = sum((Decimal(r['payable']) for r in ledger), Decimal('0'))
    business_payable = Decimal(business.get('payable', '0'))
    checks.append(_check('PAYABLE_SUM', '应付独立求和一致',
                         row_payable == ledger_payable == business_payable,
                         str(row_payable)))
    return checks


def balance(state):
    accepted = len(state['rows']); isolated = len(state['quarantine'])
    accounted = accepted + isolated + state['blank_count'] + state['header_count'] + state['duplicate_count']
    row_balanced = accounted == state['input_count']
    checks = approval_checks(state)
    conservation_ok = all(item['ok'] for item in checks)
    return {'input': state['input_count'], 'accepted': accepted, 'isolated': isolated,
            'blank': state['blank_count'], 'headers': state['header_count'],
            'duplicates': state['duplicate_count'], 'accounted': accounted,
            'balanced': row_balanced and conservation_ok,
            'checks': checks,
            'approval_issues': len(state.get('approval_issues', [])),
            'business': state.get('business', {})}
