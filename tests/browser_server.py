"""Disposable loopback-only browser fixture. Never use as the product server."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dataclasses import replace
import uuid
import argparse

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import uvicorn

from gamepersona.web.config import load_settings
from gamepersona.web.app import create_app
from gamepersona.web.worker import AssessmentEngine
from gamepersona.storage import Store,read_json,content_hash


class FixtureVerifier:
    def login_url(self,origin,return_to):
        return return_to+'&fixture=valid'

    def verify(self,parameters,return_to):
        return '76561190000000001' if parameters.get('fixture')=='valid' else None


class FixtureEngine(AssessmentEngine):
    def assess(self,*args):
        report=super().assess(*args)
        report['label'] += ' · 浏览器验收样例（登录和采集为测试替身）'
        report.pop('report_sha256')
        report['report_sha256']=content_hash(report)
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8001)
    parser.add_argument('--scenario',choices=['normal','zero','partial'],default='normal')
    args=parser.parse_args()
    settings=load_settings()
    schema='browser_'+uuid.uuid4().hex
    with psycopg.connect(settings.database_url,autocommit=True) as con:
        con.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    fixture_settings=replace(settings,database_url=make_conninfo(settings.database_url,options=f'-c search_path={schema}'),
                             origin=f'http://127.0.0.1:{args.port}',worker_enabled=True,steam_api_key='fixture')
    def collector(*_):
        records=read_json(Path('artifacts/snapshots/stage1-steam-20261013-01/records.json'))
        games=[{'appid':r['app_id'],'playtime_forever':r['duration_hours']*60 if r['duration_hours'] is not None else None} for r in records if r['app_id']]
        if args.scenario=='zero':
            games=[{**g,'playtime_forever':0} for g in games]
        elif args.scenario=='partial':
            games=[g for g in games if g['playtime_forever'] and g['playtime_forever']>0][:6]
        return 'success',games
    app=create_app(fixture_settings,verifier=FixtureVerifier(),collector=collector,
                   engine=FixtureEngine(Store(settings.root)))
    try:
        uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)
    finally:
        with psycopg.connect(settings.database_url,autocommit=True) as con:
            con.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__=='__main__':
    main()
