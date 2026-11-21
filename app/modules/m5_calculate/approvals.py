"""审批单解析与校验。

审批单有两种等价形态：
1. parameters['approvals']：[{"order_id": "...", "employee": "...", "approved_minutes": 120}, ...]
2. parameters['approvals_csv']：与形态1同字段的 CSV 文本（带不带 BOM 均可）。

解析产物为 (orders, issues)：
- orders：通过校验的单据列表，分钟为 int；
- issues：结构/取值问题，进入 state['approval_issues']，不污染打卡隔离表。
审批单只写员工与总分钟，不指定片段；落段裁决见 allocation.py。
"""
import csv
import io
from decimal import Decimal, InvalidOperation

REQUIRED_FIELDS = ('order_id', 'employee', 'approved_minutes')


def _coerce_minutes(value):
    """审批分钟必须是非负整数；哨兵、小数、负数一律拒绝。"""
    if value is None:
        raise ValueError('MISSING')
    text = str(value).strip()
    if text in ('', '-', 'N/A', 'NULL', '未知'):
        raise ValueError('MISSING')
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError('APPROVAL_MINUTES')
    if number != number.to_integral_value() or number < 0:
        raise ValueError('APPROVAL_MINUTES')
    return int(number)


def _normalize(record, source):
    if not isinstance(record, dict):
        return None, {'code': 'APPROVAL_SHAPE', 'order_id': '', 'employee': '', 'raw': str(record), 'source': source}
    order_id = str(record.get('order_id', '')).strip()
    employee = str(record.get('employee', '')).strip()
    if not order_id or not employee:
        return None, {'code': 'APPROVAL_SHAPE', 'order_id': order_id, 'employee': employee,
                      'raw': record, 'source': source}
    try:
        minutes = _coerce_minutes(record.get('approved_minutes'))
    except ValueError as error:
        return None, {'code': error.args[0], 'order_id': order_id, 'employee': employee,
                      'raw': record, 'source': source}
    return {'order_id': order_id, 'employee': employee, 'approved_minutes': minutes, 'source': source}, None


def parse_csv(text):
    if not isinstance(text, str):
        raise ValueError('APPROVAL_CSV')
    reader = csv.DictReader(io.StringIO(text.lstrip('﻿')))
    if reader.fieldnames is None or not set(REQUIRED_FIELDS).issubset(set(reader.fieldnames)):
        raise ValueError('APPROVAL_HEADER')
    rows = []
    for raw in reader:
        rows.append({key: (raw.get(key, '') or '').strip() for key in REQUIRED_FIELDS})
    return rows


def parse(parameters):
    """返回 (orders, issues)。同 order_id 重复的整组单据按 APPROVAL_DUPLICATE 隔离。"""
    parameters = parameters or {}
    raw_records = []
    if isinstance(parameters.get('approvals'), list):
        raw_records.extend(('json', item) for item in parameters['approvals'])
    if 'approvals_csv' in parameters:
        try:
            raw_records.extend(('csv', item) for item in parse_csv(parameters['approvals_csv']))
        except ValueError as error:
            return [], [{'code': error.args[0], 'order_id': '', 'employee': '', 'raw': {}, 'source': 'csv'}]
    orders, issues = [], []
    for source, record in raw_records:
        order, issue = _normalize(record, source)
        (orders if order else issues).append(order if order else issue)
    # 同一审批单号重复（无论内容是否一致）都不允许静默合并，整组隔离。
    seen = {}
    for order in orders:
        seen.setdefault(order['order_id'], []).append(order)
    duplicated = {oid for oid, group in seen.items() if len(group) > 1}
    clean = []
    for order in orders:
        if order['order_id'] in duplicated:
            issues.append({'code': 'APPROVAL_DUPLICATE', 'order_id': order['order_id'],
                           'employee': order['employee'], 'raw': order, 'source': order['source']})
        else:
            clean.append(order)
    return clean, issues
