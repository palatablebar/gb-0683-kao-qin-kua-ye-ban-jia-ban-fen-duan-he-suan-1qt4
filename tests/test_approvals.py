"""审批额度落段裁决（RATE_FIRST）测试。"""
import pytest
from decimal import Decimal
from app.workflow import run, load, default_parameters
from app.modules.m5_calculate.approvals import parse as parse_approvals
from app.modules.m5_calculate.allocation import allocate, POLICY
from app.modules.m5_calculate.rules import price


def seg(day, start, minutes, multiplier_rate=('20',)):
    rate = multiplier_rate[0]
    end_minutes = minutes
    return {'id': 'S', 'employee': 'E', 'shift_day': day, 'calendar_day': day,
            'start': day + 'T' + start, 'end': day + 'T' + start, 'minutes': minutes,
            'rate': rate, 'line': 1, 'multiplier': '1', 'code': 'REGULAR', 'amount': '0'}


def priced_two_rates():
    """模拟题面结构：较早段为工作日 1 倍 300 分钟，跨进国庆后假日段 3 倍 120 分钟，时薪 20。"""
    normal = seg('2026-09-30', '22:00', 300)
    normal.update(multiplier='1', code='REGULAR',
                  amount=str((Decimal('20') * 300 / 60).quantize(Decimal('0.01'))))
    holiday = seg('2026-10-01', '03:00', 120)
    holiday.update(multiplier='3', code='HOLIDAY',
                   amount=str((Decimal('20') * 120 * 3 / 60).quantize(Decimal('0.01'))))
    return [normal, holiday]


def test_rate_first_high_multiplier_consumes_quota_first():
    rows = priced_two_rates()
    orders = [{'order_id': 'A1', 'employee': 'E', 'approved_minutes': 200, 'source': 'json'}]
    out, ledger, issues = allocate(rows, orders)
    normal, holiday = out
    # 裁决：尽管假日段发生更晚，高倍率（3x）仍先吃满 120，剩余 80 落到较早的 1x 段。
    assert holiday['approved_minutes'] == 120 and holiday['allocation_rank'] == 1
    assert normal['approved_minutes'] == 80 and normal['unapproved_minutes'] == 220
    assert holiday['allocation_policy'] == POLICY and holiday['order_ids'] == ['A1']
    assert ledger[0]['approved_minutes'] == 200 and ledger[0]['unapproved_minutes'] == 220


def test_rate_first_pays_more_than_chronological():
    """量化裁决收益：同 100 分钟额度（不够覆盖整段假日），高倍率优先的应付严格大于先到先得。"""
    def money(ordering):
        rows = priced_two_rates()
        ranked = sorted(rows, key=ordering)
        remaining = 100
        total = Decimal('0')
        for r in ranked:
            approved = min(remaining, r['minutes']); remaining -= approved
            total += Decimal(r['amount']) * approved / r['minutes']
        return total.quantize(Decimal('0.01'))
    rate_first = money(lambda r: -Decimal(r['multiplier']))
    chronological = money(lambda r: r['start'])
    # 100 分钟：3x 段每 100 分钟 100 元；先到先得落在 1x 段仅 33.33 元。
    assert rate_first == Decimal('100.00') and chronological == Decimal('33.33')
    assert rate_first > chronological


def test_minute_conservation_every_row():
    rows = priced_two_rates()
    out, ledger, _ = allocate(rows, [{'order_id': 'A1', 'employee': 'E', 'approved_minutes': 999, 'source': 'json'}])
    for r in out:
        assert r['minutes'] == r['approved_minutes'] + r['unapproved_minutes']
    # 批而未用：额度 999，实际 420，余量 579 不挪用、不累计。
    assert ledger[0]['unused_approval_minutes'] == 579
    assert ledger[0]['approved_minutes'] == 420


def test_cash_conservation_payable_plus_withheld_equals_amount():
    rows = priced_two_rates()
    out, _, _ = allocate(rows, [{'order_id': 'A1', 'employee': 'E', 'approved_minutes': 200, 'source': 'json'}])
    for r in out:
        assert Decimal(r['payable']) + Decimal(r['withheld']) == Decimal(r['amount'])


def test_no_approval_means_all_unapproved_zero_payable():
    rows = priced_two_rates()
    out, ledger, issues = allocate(rows, [])
    assert all(r['approved_minutes'] == 0 and r['payable'] == '0.00' for r in out)
    assert all(r['unapproved_minutes'] == r['minutes'] for r in out)
    assert ledger[0]['payable'] == '0.00' and not issues


def test_unmatched_approval_is_issue_not_consumed():
    rows = priced_two_rates()
    orders = [{'order_id': 'A9', 'employee': 'GHOST', 'approved_minutes': 90, 'source': 'csv'}]
    _, ledger, issues = allocate(rows, orders)
    assert any(i['code'] == 'APPROVAL_UNMATCHED' and i['order_id'] == 'A9' for i in issues)
    assert all(r['approved_minutes'] == 0 for r in ledger)


def test_equal_rate_tie_breaks_chronologically():
    a = seg('2026-10-02', '09:00', 60); a.update(multiplier='1', amount='20.00')
    b = seg('2026-10-02', '15:00', 60); b.update(multiplier='1', amount='20.00')
    out, _, _ = allocate([a, b], [{'order_id': 'A1', 'employee': 'E', 'approved_minutes': 60, 'source': 'json'}])
    assert out[0]['allocation_rank'] == 1 and out[0]['approved_minutes'] == 60
    assert out[1]['approved_minutes'] == 0


def test_parse_approvals_json_and_csv():
    orders, issues = parse_approvals({'approvals': [
        {'order_id': 'A1', 'employee': 'E1', 'approved_minutes': 30}]})
    assert orders == [{'order_id': 'A1', 'employee': 'E1', 'approved_minutes': 30, 'source': 'json'}]
    orders, issues = parse_approvals({'approvals_csv': 'order_id,employee,approved_minutes\nA2,E2,45\n'})
    assert orders[0]['order_id'] == 'A2' and orders[0]['approved_minutes'] == 45 and orders[0]['source'] == 'csv'


def test_parse_rejects_bad_minutes_and_missing_fields():
    _, issues = parse_approvals({'approvals': [
        {'order_id': 'A1', 'employee': 'E1', 'approved_minutes': -5},
        {'order_id': '', 'employee': 'E2', 'approved_minutes': 10},
        {'order_id': 'A3', 'employee': 'E3', 'approved_minutes': 12.5}]})
    codes = {i['code'] for i in issues}
    assert codes == {'APPROVAL_MINUTES', 'APPROVAL_SHAPE'}


def test_duplicate_order_id_quarantined_whole_group():
    _, issues = parse_approvals({'approvals': [
        {'order_id': 'A1', 'employee': 'E1', 'approved_minutes': 10},
        {'order_id': 'A1', 'employee': 'E1', 'approved_minutes': 10}]})
    assert all(i['code'] == 'APPROVAL_DUPLICATE' for i in issues) and len(issues) == 2


def test_bad_csv_header_returns_issue():
    _, issues = parse_approvals({'approvals_csv': 'foo,bar\n1,2\n'})
    assert issues and issues[0]['code'] == 'APPROVAL_HEADER'


def test_end_to_end_run_with_sample_approvals(raw):
    state = run(raw, default_parameters())
    e1 = [r for r in state['calculations'] if r['employee'] == 'E001']
    # E001 额度 300：假日 3x 段（120 分钟）先满，再覆盖普通段 180 分钟。
    holiday = next(r for r in e1 if r['code'] == 'HOLIDAY')
    assert holiday['approved_minutes'] == 120
    assert sum(r['approved_minutes'] for r in e1) == 300
    assert sum(r['unapproved_minutes'] for r in e1) == 120
    # E999 审批单无匹配 -> 异常留痕，不进任何片段。
    assert any(i['code'] == 'APPROVAL_UNMATCHED' for i in state['approval_issues'])
    assert state['reconcile']['balanced'] is True


def test_business_totals_correspond_item_by_item(raw):
    state = run(raw, default_parameters())
    b = state['business']
    assert b['minutes'] == b['approved_minutes'] + b['unapproved_minutes']
    assert Decimal(b['payable']) + Decimal(b['withheld']) == Decimal(b['total'])
    assert sum(Decimal(r['payable']) for r in state['calculations']) == Decimal(b['payable'])


def test_approval_change_invalidates_and_recomputes(raw):
    """审批一更新，run_id 变化，旧结果作废重算且不丢记录。"""
    first = run(raw, {'approvals': [{'order_id': 'A1', 'employee': 'E001', 'approved_minutes': 60}]})
    second = run(raw, {'approvals': [{'order_id': 'A1', 'employee': 'E001', 'approved_minutes': 300}]})
    assert first['run_id'] != second['run_id']
    assert first['business']['payable'] != second['business']['payable']
    # 同输入重复执行幂等：run_id 相同，结果一致。
    again = run(raw, {'approvals': [{'order_id': 'A1', 'employee': 'E001', 'approved_minutes': 60}]})
    assert again['run_id'] == first['run_id'] and again['business']['payable'] == first['business']['payable']
