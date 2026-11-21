from app.modules.m7_archive.export_out import checksum


def execute(state):
    state['archive'] = {
        'sha256': checksum(state),
        'evidence_count': len(state.get('calculations', [])) + len(state['quarantine'])
        + len(state.get('approval_ledger', [])) + len(state.get('approval_issues', [])),
        'ready': state.get('reconcile', {}).get('balanced', False),
        'sealable': state.get('reconcile', {}).get('balanced', False),
    }
    return state
