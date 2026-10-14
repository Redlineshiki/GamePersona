"""Immutable assessments from a fixed Steam input and compatible reference."""
from .features import pin_input, verify_pins
from .scoring import score_records
from .reference import build_report
from .interpretation import share_projection
from .storage import Store, read_json, write_json


def calculate_assessment(store: Store, pins: dict) -> dict:
    verify_pins(store,pins)
    rp = store.path(pins['reference']['snapshot'])
    sm = store.load(pins['steam']['snapshot'],'steam')
    model,ref = read_json(rp/'model.json'),read_json(rp/'reference.json')
    return build_report(score_records(read_json(store.path(pins['steam']['snapshot'])/'records.json'),
                                     read_json(rp/'features.json'),model,sm['read_status']),
                        ref,model,pins['steam']['snapshot'])


def score_steam(store: Store, snapshot: str, steam: str, reference: str) -> dict:
    pins = {'steam':pin_input(store,steam,'steam',['records.json']),
            'reference':pin_input(store,reference,'reference',['model.json','reference.json','features.json'])}
    report = calculate_assessment(store,pins)
    path,manifest = store.create(snapshot,'assessment',{'inputs':pins,'version':'report-v1'})
    write_json(path/'report.json',report)
    write_json(path/'share.json',share_projection(report))
    store.finish(path,manifest,report_sha256=report['report_sha256'])
    return report


def replay_score(store: Store, snapshot: str) -> dict:
    manifest = store.load(snapshot,'assessment')
    store.verify(snapshot)
    report = calculate_assessment(store,manifest['config']['inputs'])
    if report != read_json(store.path(snapshot)/'report.json') or share_projection(report)!=read_json(store.path(snapshot)/'share.json'):
        raise ValueError('固定报告离线重算不一致')
    return {'status':'identical','report_sha256':report['report_sha256']}
