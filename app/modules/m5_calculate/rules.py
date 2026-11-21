from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from app.modules.m5_calculate.approvals import parse as parse_approvals
from app.modules.m5_calculate.allocation import allocate, POLICY


def price(segments, holidays):
    normal_used = defaultdict(int); out = []
    for s in sorted(segments, key=lambda r: (r['start'], r['employee'])):
        d = date.fromisoformat(s['calendar_day']); key = (s['employee'], s['calendar_day'])
        minutes = s['minutes']; rate = Decimal(str(s['rate']))
        if s['calendar_day'] in holidays: parts = [(minutes, Decimal(3), 'HOLIDAY')]
        elif d.weekday() >= 5: parts = [(minutes, Decimal(2), 'REST')]
        else:
            regular = min(minutes, max(0, 480 - normal_used[key])); normal_used[key] += minutes
            parts = [(regular, Decimal(1), 'REGULAR'), (minutes - regular, Decimal('1.5'), 'OVERTIME')]
        for count, multiplier, code in parts:
            if count:
                item = dict(s)
                item.update(minutes=count, multiplier=str(multiplier), code=code,
                            amount=str((rate * count * multiplier / 60).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)))
                out.append(item)
    return out


def apply(state):
    holidays = set(state['parameters'].get('holidays', ['2026-10-01']))
    calculations = price(state['segments'], holidays)
    orders, issues = parse_approvals(state['parameters'])
    calculations, ledger, issues = allocate(calculations, orders, issues)
    total = sum((Decimal(r['amount']) for r in calculations), Decimal(0))
    payable = sum((Decimal(r['payable']) for r in calculations), Decimal(0))
    withheld = sum((Decimal(r['withheld']) for r in calculations), Decimal(0))
    paid = sum((Decimal(str(r['paid'])) for r in state['rows']), Decimal(0))
    approved_minutes = sum(r['approved_minutes'] for r in calculations)
    unapproved_minutes = sum(r['unapproved_minutes'] for r in calculations)
    state['calculations'] = calculations
    state['approval_ledger'] = ledger
    state['approval_issues'] = issues
    state['business'] = {
        'total': str(total), 'paid': str(paid), 'difference': str(total - paid),
        'payable': str(payable.quantize(Decimal('.01'))),
        'withheld': str(withheld.quantize(Decimal('.01'))),
        'minutes': sum(r['minutes'] for r in calculations),
        'approved_minutes': approved_minutes,
        'unapproved_minutes': unapproved_minutes,
        'allocation_policy': POLICY, 'unit': 'CNY',
    }
    return state
