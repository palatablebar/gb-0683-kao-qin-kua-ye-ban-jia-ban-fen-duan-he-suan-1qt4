"""封存发布、版本失效、页面与导出同源测试。"""
import pytest
from app import store
from app.workflow import run, load, default_parameters
from app.errors import DomainError
from app.modules.m7_archive.export_out import bundle


def _run(client_sample=None, params=None):
    return run(load('dirty.csv'), params or default_parameters())


def test_seal_requires_balanced_reconcile(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 's.db'))
    state = _run()
    store.save(state['run_id'], state)
    sealed = store.seal(state['run_id'])
    assert sealed['sealed'] is True and sealed['sealed_at']


def test_seal_blocks_when_unbalanced(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 's.db'))
    state = _run()
    state['reconcile']['balanced'] = False  # 人为制造对账不平
    store.save(state['run_id'], state)
    with pytest.raises(DomainError) as e:
        store.seal(state['run_id'])
    assert e.value.status == 409 and e.value.code == 'UNBALANCED'
    # 失败后旧版仍未封存、原始依据仍在。
    got = store.get(state['run_id'])
    assert got['sealed'] is False and got['source_b64']


def test_double_seal_rejected_keeps_first(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 's.db'))
    state = _run(); store.save(state['run_id'], state)
    first_at = store.seal(state['run_id'])['sealed_at']
    with pytest.raises(DomainError) as e:
        store.seal(state['run_id'])
    assert e.value.code == 'SEALED'
    assert store.get(state['run_id'])['sealed_at'] == first_at


def test_new_run_marks_old_superseded_but_keeps_records(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 's.db'))
    first = _run(params={'approvals': [{'order_id': 'A1', 'employee': 'E001', 'approved_minutes': 60}]})
    store.save(first['run_id'], first)
    second = _run(params={'approvals': [{'order_id': 'A1', 'employee': 'E001', 'approved_minutes': 300}]})
    store.save(second['run_id'], second)
    history = {h['id']: h for h in store.history()}
    assert history[first['run_id']]['superseded'] is True
    assert history[second['run_id']]['superseded'] is False
    # 旧批次整份可取，证据不丢。
    assert store.get(first['run_id'])['calculations'] == first['calculations']


def test_repeated_submit_does_not_double_consume(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 's.db'))
    state = _run()
    store.save(state['run_id'], state); store.save(state['run_id'], state)
    assert len(store.history()) == 1
    assert store.get(state['run_id'])['business']['approved_minutes'] == state['business']['approved_minutes']


def test_export_and_page_share_same_result(client):
    submitted = client.post('/api/runs', json={'sample': 'dirty.csv'}).get_json()
    export = client.get('/api/archive/' + submitted['run_id'] + '/export.csv').data.decode('utf-8-sig')
    page = client.get('/m5_calculate').data.decode()
    # 页面与导出共用同一份 run：应付金额与审批台账在两处一致出现。
    assert '审批台账' in export and submitted['business']['payable'] in export
    assert submitted['business']['payable'] in page
    assert submitted['run_id'] in page


def test_export_contains_allocation_evidence(client):
    submitted = client.post('/api/runs', json={'sample': 'dirty.csv'}).get_json()
    export = client.get('/api/archive/' + submitted['run_id'] + '/export.csv').data.decode('utf-8-sig')
    for token in ('运行清单', '对账', '审批台账', '审批异常', 'RATE_FIRST'):
        assert token in export


def test_seal_endpoint_and_unbalanced_export_gate(client):
    run_id = client.post('/api/runs', json={'sample': 'dirty.csv'}).get_json()['run_id']
    ok = client.post('/api/runs/' + run_id + '/seal')
    assert ok.status_code == 200 and ok.get_json()['sealed'] is True
    again = client.post('/api/runs/' + run_id + '/seal')
    assert again.status_code == 409 and again.get_json()['code'] == 'SEALED'


def test_reconcile_checks_all_pass_on_real_pipeline(client):
    data = client.post('/api/runs', json={'sample': 'dirty.csv'}).get_json()
    checks = data['reconcile']['checks']
    assert len(checks) >= 4 and all(c['ok'] for c in checks)


def test_archive_page_renders_superseded_state(client):
    client.post('/api/runs', json={'sample': 'dirty.csv'})
    client.post('/api/runs', json={'sample': 'clean.csv'})
    page = client.get('/m7_archive').data.decode()
    assert '已作废' in page and '封存当前批次' in page


def test_unbalanced_run_blocks_export_and_seal(client):
    run_id = client.post('/api/runs', json={'sample': 'dirty.csv'}).get_json()['run_id']
    # 直接破坏已存批次的对账结论，模拟发布前发现不平。
    from app import store
    body = store.get(run_id); body['reconcile']['balanced'] = False
    with store.connection() as db:
        import json as _json
        db.execute('UPDATE runs SET body=? WHERE id=?', (_json.dumps(body, ensure_ascii=False), run_id))
    assert client.get('/api/archive/' + run_id + '/export.csv').status_code == 409
    seal = client.post('/api/runs/' + run_id + '/seal')
    assert seal.status_code == 409 and seal.get_json()['code'] == 'UNBALANCED'
    assert store.get(run_id)['sealed'] is False
