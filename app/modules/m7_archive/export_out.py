import io, csv, json, hashlib


def bundle(state):
    out = io.StringIO(newline=''); writer = csv.writer(out)
    writer.writerow(['记录类型', '批次', '来源行', '业务ID', '原因码', '内容'])
    rid = state.get('run_id', 'preview')
    writer.writerow(['运行清单', rid, '', '', '', json.dumps(state.get('manifest', {}), ensure_ascii=False, sort_keys=True)])
    writer.writerow(['对账', rid, '', '', '', json.dumps(state.get('reconcile', {}), ensure_ascii=False, sort_keys=True)])
    for row in state.get('approval_ledger', []):
        writer.writerow(['审批台账', rid, '', row.get('employee', ''), row.get('allocation_policy', ''),
                         json.dumps(row, ensure_ascii=False, sort_keys=True)])
    for issue in state.get('approval_issues', []):
        writer.writerow(['审批异常', rid, '', issue.get('employee', ''), issue.get('code', ''),
                         json.dumps(issue, ensure_ascii=False, sort_keys=True)])
    for row in state.get('calculations', []):
        writer.writerow(['计算', rid, row.get('line', ''), row.get('id', ''), row.get('code', ''),
                         json.dumps(row, ensure_ascii=False, sort_keys=True)])
    for row in state['quarantine']:
        writer.writerow(['隔离', rid, row['line'], row.get('id', ''), row['code'], json.dumps(row.get('raw', {}), ensure_ascii=False, sort_keys=True)])
    return '﻿' + out.getvalue()


def checksum(state):
    return hashlib.sha256(bundle(state).encode('utf-8')).hexdigest()
