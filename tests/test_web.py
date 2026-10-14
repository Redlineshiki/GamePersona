"""Real PostgreSQL integration; isolated schemas, no production authentication bypass."""
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
import secrets
import uuid
import time
from urllib.parse import urlparse,parse_qs

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient
import pytest

from gamepersona.features import DIMENSIONS
from gamepersona.scoring import model_config,score_records
from gamepersona.reference import make_reference,build_report,FIXED_BOUNDS
from gamepersona.web.config import load_settings
from gamepersona.web.app import create_app, COOKIE, LOGIN_COOKIE
from gamepersona.web.auth import SteamOpenID,token_hash,STEAM_OP,OPENID_NS
from gamepersona.storage import content_hash
from contextlib import contextmanager


class FixtureEngine:
    def __init__(self):
        self.features = [{"app_id":i,"rule_version":"fixture","modes":{"combined":{"complete":True,"eligible":True,
                         "values":dict.fromkeys(DIMENSIONS,1.),"matches":{}}}} for i in range(1,11)]
        self.model = model_config(min_reference=3)
        fitting=[]
        for h in (10,15,20,30):
            s=score_records([{'app_id':i,'duration_hours':h} for i in range(1,7)],self.features,self.model)
            fitting.append({'N':s['N'],'H_ticks':s['H_ticks'],'coverage':s['coverage'],'unknown_ratio':0,
                            **{f'E_{k}':s['evidence_ticks'][k] for k in DIMENSIONS}})
        self.ref=make_reference(fitting,self.model,FIXED_BOUNDS,{'reference':'fixture','feature':'fixture'})

    def load(self,reference):
        pass

    def assess(self,records,status,reference,input_id):
        return build_report(score_records(records,self.features,self.model,status),self.ref,self.model,input_id)


class FixtureVerifier:
    def login_url(self,origin,return_to):
        return return_to

    def verify(self,parameters,return_to):
        return '76561190000000001' if parameters.get('fixture')=='valid' else None


@pytest.fixture
def web_settings():
    if not Path('.env.web').exists():
        pytest.skip('PostgreSQL integration requires local .env.web')
    settings=load_settings()
    schema='test_'+uuid.uuid4().hex
    with psycopg.connect(settings.database_url,autocommit=True) as con:
        con.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    yield replace(settings,database_url=make_conninfo(settings.database_url,options=f'-c search_path={schema}'),worker_enabled=False,steam_api_key='fixture')
    with psycopg.connect(settings.database_url,autocommit=True) as con:
        con.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.fixture
def client(web_settings):
    app=create_app(web_settings,verifier=FixtureVerifier(),engine=FixtureEngine(),
                   collector=lambda *_:('success',[{'appid':i,'name':f'Private game {i}','playtime_forever':1200} for i in range(1,7)]))
    with TestClient(app,base_url=web_settings.origin) as c:
        yield c


def signin(client):
    start=client.get('/auth/steam',follow_redirects=False)
    returned=start.headers['location']+'&fixture=valid'
    assert client.get(returned,follow_redirects=False).status_code==303
    s=client.get('/api/session').json()
    assert s['authenticated']
    return {'origin':client.app.state.settings.origin,'x-csrf-token':s['csrf']}


def test_login_binding_replay_cancel_and_host(client):
    r=client.get('/auth/steam',follow_redirects=False)
    original=client.cookies.get(client.app.state.login_cookie_name)
    client.cookies.clear()
    assert client.get(r.headers['location']+'&fixture=valid').status_code==400
    client.cookies.set(client.app.state.login_cookie_name,original)
    assert client.get(r.headers['location']+'&fixture=valid',follow_redirects=False).status_code==303
    assert client.get(r.headers['location']+'&fixture=valid').status_code==400
    assert client.get('/api/session',headers={'host':'evil.example'}).status_code==400


def test_saved_report_recompute_preserves_history_and_collection(client):
    from gamepersona.web.recompute import recompute_saved_reports
    headers=signin(client)
    task=client.post('/api/assessments',headers=headers).json()['task_id']
    client.app.state.worker.run_once()
    old_id=client.get(f'/api/tasks/{task}').json()['report_id']
    previous=client.get(f'/api/reports/{old_id}').json()
    engine=client.app.state.worker.engine
    engine.ref['versions']['reference']='new-W-test'
    result=recompute_saved_reports(client.app.state.db,engine,'new-W-test')
    assert result['updated_reports']==1
    new_id=client.get('/api/reports').json()[0]['id']
    new=client.get(f'/api/reports/{new_id}').json()
    assert new_id!=old_id and new['versions']['reference']=='new-W-test'
    assert new['collection']['collected_at']==previous['collection']['collected_at']
    assert new['game_names']==previous['game_names'] and new['collection']['recomputed_at']
    assert client.get(f'/api/reports/{old_id}').json()==previous
    assert recompute_saved_reports(client.app.state.db,engine,'new-W-test')['updated_reports']==0


def test_csrf_tasks_reports_share_and_another_user(client):
    headers=signin(client)
    assert client.post('/api/assessments').status_code==403
    assert client.post('/api/assessments',headers={**headers,'origin':'https://evil.example'}).status_code==403
    task=client.post('/api/assessments',headers=headers).json()['task_id']
    assert client.post('/api/assessments',headers=headers).json()['task_id']==task
    assert client.app.state.worker.run_once()
    result=client.get('/api/tasks/'+task).json()
    assert result['state']=='succeeded'
    report_id=result['report_id']
    report=client.get('/api/reports/'+report_id).json()
    share=client.get('/api/reports/'+report_id+'/share').json()
    assert share['report_sha256']==report['report_sha256']
    assert 'score' not in share and 'steam_id' not in share and 'contributions' not in share
    assert len(share['dimensions'])==12
    assert report['game_names']['1']=='Private game 1' and 'game_names' not in share
    with client.app.state.db.connect() as con:
        other=uuid.uuid4().hex;token=secrets.token_urlsafe(32)
        con.execute('INSERT INTO users(id,steam_id) VALUES(%s,%s)',(other,'76561190000000002'))
        con.execute("INSERT INTO sessions VALUES(%s,%s,%s,now()+interval '1 hour')",(token_hash(token),other,'test'))
    client.cookies.clear();client.cookies.set(client.app.state.cookie_name,token)
    assert client.get('/api/tasks/'+task).status_code==404
    assert client.get('/api/reports/'+report_id).status_code==404
    assert client.get('/api/reports/'+report_id+'/share').status_code==404


def test_logout_cookie_revoked(client):
    headers=signin(client);cookie=client.cookies.get(client.app.state.cookie_name)
    assert client.post('/api/logout',headers=headers).status_code==200
    client.cookies.set(client.app.state.cookie_name,cookie)
    assert not client.get('/api/session').json()['authenticated']


def test_delete_during_collection_cannot_recreate_private_data(client):
    headers=signin(client)
    client.post('/api/assessments',headers=headers)
    def deleting_collector(*_):
        assert client.delete('/api/account',headers=headers).status_code==200
        return 'success',[{'appid':1,'playtime_forever':100}]
    client.app.state.worker.collector=deleting_collector
    client.app.state.worker.run_once()
    with client.app.state.db.connect() as con:
        for table in ('users','sessions','tasks','reports','input_snapshots','login_transactions'):
            assert con.execute(sql.SQL('SELECT count(*) n FROM {}').format(sql.Identifier(table))).fetchone()['n']==0


def test_read_failure_not_saved_as_zero_library(client):
    headers=signin(client)
    task=client.post('/api/assessments',headers=headers).json()['task_id']
    client.app.state.worker.collector=lambda *_:('timeout',[])
    client.app.state.worker.run_once()
    assert client.get('/api/tasks/'+task).json()['state']=='failed'
    assert client.get('/api/reports').json()==[]


def test_real_library_openid_signature_nonce_and_required_signed_fields(client):
    def provider(request):
        assert str(request.url)==STEAM_OP
        return httpx.Response(200,text='ns:'+OPENID_NS+'\nis_valid:true\n')
    verifier=SteamOpenID(client.app.state.db,lambda **kw:httpx.Client(transport=httpx.MockTransport(provider),**kw))
    now=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return_to=client.app.state.settings.origin+'/auth/callback?state=fixture'
    claimed='https://steamcommunity.com/openid/id/76561190000000001'
    params={'openid.ns':OPENID_NS,'openid.mode':'id_res','openid.op_endpoint':STEAM_OP,
            'openid.return_to':return_to,'openid.claimed_id':claimed,'openid.identity':claimed,
            'openid.response_nonce':now+'fixture','openid.assoc_handle':'fixture','openid.sig':'fixture',
            'openid.signed':'op_endpoint,return_to,response_nonce,assoc_handle,claimed_id,identity','state':'fixture'}
    assert verifier.verify(params,return_to)=='76561190000000001'
    assert verifier.verify(params,return_to) is None
    assert verifier.verify({**params,'openid.op_endpoint':'https://evil.example'},return_to) is None
    assert verifier.verify({**params,'openid.signed':'op_endpoint','openid.response_nonce':now+'second'},return_to) is None


def test_worker_recovers_interrupted_tasks_with_schema_scoped_leader_lock(client):
    headers=signin(client)
    task=client.post('/api/assessments',headers=headers).json()['task_id']
    with client.app.state.db.connect() as con:
        con.execute("UPDATE tasks SET state='running' WHERE id=%s",(task,))
    # A different namespace may hold its leader lock without starving this worker.
    with psycopg.connect(load_settings().database_url,autocommit=True) as leader:
        leader.execute("SELECT pg_advisory_lock(hashtext('public'),53170002)")
        worker=client.app.state.worker
        worker.start()
        try:
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                result=client.get('/api/tasks/'+task).json()
                if result['state']=='succeeded':break
                time.sleep(.05)
            assert result['state']=='succeeded'
        finally:
            worker.stop()


def test_worker_reconnects_after_temporary_database_failure(client):
    headers=signin(client)
    task=client.post('/api/assessments',headers=headers).json()['task_id']
    real=client.app.state.db
    class UnavailableOnce:
        calls=0
        @contextmanager
        def connect(self):
            self.calls+=1
            if self.calls==1:
                raise psycopg.OperationalError('synthetic outage')
            with real.connect() as con:yield con
    worker=client.app.state.worker;worker.db=UnavailableOnce()
    worker.start()
    try:
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            result=client.get('/api/tasks/'+task).json()
            if result['state']=='succeeded':break
            time.sleep(.05)
        assert result['state']=='succeeded'
    finally:worker.stop()


def test_fixed_report_survives_service_recreation_and_keeps_hash(client):
    headers=signin(client)
    task=client.post('/api/assessments',headers=headers).json()['task_id']
    client.app.state.worker.run_once()
    report_id=client.get('/api/tasks/'+task).json()['report_id']
    original=client.get('/api/reports/'+report_id).json()
    payload=dict(original);digest=payload.pop('report_sha256')
    assert content_hash(payload)==digest
    token=client.cookies.get(client.app.state.cookie_name)
    recreated=create_app(client.app.state.settings,verifier=FixtureVerifier(),engine=FixtureEngine())
    with TestClient(recreated,base_url=client.app.state.settings.origin) as reopened:
        reopened.cookies.set(recreated.state.cookie_name,token)
        assert reopened.get('/api/reports/'+report_id).json()==original
