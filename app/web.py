import base64
from flask import request, render_template, jsonify
from app.errors import DomainError
from app.config import TITLE, MODULES, SHORT
from app.workflow import run, load, default_parameters
from app import store

def payload():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict): raise DomainError('PAYLOAD', '请求必须是对象')
    if 'csv' in data and not isinstance(data['csv'], str): raise DomainError('CSV', 'CSV内容必须是文本')
    sample = data.get('sample', request.args.get('sample', 'dirty.csv'))
    content = data.get('csv')
    parameters = data.get('parameters', {})
    # 未显式给参数时，页面与接口共用样例审批单，保证落段结果可演示、可复算。
    if not parameters:
        parameters = default_parameters()
    return (content.encode() if isinstance(content, str) else load(sample)), parameters

def api(stage):
    content,parameters=payload();return jsonify(run(content,parameters,stage))

def page(stage, template):
    latest = store.history(); state = store.get(latest[0]['id']) if latest else run(load('dirty.csv'), default_parameters())
    source = load(request.args['sample']) if 'sample' in request.args else base64.b64decode(state['source_b64']) if state.get('source_b64') else load('dirty.csv')
    parameters = state.get('manifest', {}).get('parameters', {}) or default_parameters()
    data = run(source, parameters, stage)
    return render_template(template, title=TITLE, short=SHORT, modules=MODULES, current=stage, data=data, run=state, history=latest)
