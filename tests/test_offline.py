import csv
import json

from gamepersona.storage import Store,write_json,read_json
from gamepersona.ingest import import_kaggle
from gamepersona.features import DIMENSIONS
from gamepersona.offline import aggregate,replay_aggregate,CANDIDATES
from gamepersona.calibration import experiment,replay_reference
from gamepersona.scoring import score_records
from gamepersona.database import connect,literal,rows


def test_offline_integer_parity_replay_and_insufficient_reference(tmp_path):
    source=tmp_path/'input';source.mkdir()
    (source/'games.csv').write_text('app_id,title\n'+''.join(f'{i},Game{i}\n' for i in range(1,8)),encoding='utf-8')
    (source/'users.csv').write_text('user_id\n'+''.join(f'{i}\n' for i in range(60)),encoding='utf-8')
    (source/'games_metadata.json').write_text('\n'.join(json.dumps({'app_id':i,'tags':['Action']}) for i in range(1,8)),encoding='utf-8')
    with (source/'recommendations.csv').open('w',newline='',encoding='utf-8') as output:
        writer=csv.writer(output);writer.writerow(['app_id','user_id','review_id','hours','date','is_recommended'])
        for user in range(60):
            for app in range(1,8):writer.writerow([app,user,f'{user}-{app}',(user+1)*app/10,'2024-01-01','true'])
    store=Store(tmp_path/'artifacts')
    import_kaggle(store,'kg',source,hours_unit='hours',hours_evidence='synthetic fixture',memory_limit='256MiB',threads=1)
    features=[{'app_id':i,'rule_version':'fixture','modes':{'combined':{'complete':True,'eligible':True,
               'values':dict.fromkeys(DIMENSIONS,[.25,.5,1][i%3]),'matches':{}}}} for i in range(1,8)]
    path,manifest=store.create('features','features',{'inputs':{'kaggle':{'snapshot':'kg'}}})
    write_json(path/'features.json',features);write_json(path/'rules.json',{'version':'fixture'})
    store.finish(path,manifest)
    result=aggregate(store,'aggregate','kg','features')
    assert result['totals']['users']==60
    con=connect(':memory:',threads=1)
    try:
        source_records=rows(con,f"SELECT user_key,app_id,duration_hours,duration_state,exclusion_reason FROM read_parquet({literal(store.path('kg')/'normalized/records.parquet')}) WHERE user_key='kaggle:10'")
        for name,model in CANDIDATES.items():
            computed=score_records(source_records,features,model)
            sql_row=rows(con,f"SELECT * FROM read_parquet({literal(store.path('aggregate')/(name+'.parquet'))}) WHERE user_key='kaggle:10'")[0]
            assert computed['H_ticks']==sql_row['H_ticks'] and computed['N']==sql_row['N']
            assert all(computed['evidence_ticks'][k]==sql_row['E_'+k] for k in DIMENSIONS)
    finally:con.close()
    assert replay_aggregate(store,'aggregate')['status']=='identical'
    protocol=tmp_path/'protocol.md';protocol.write_text('synthetic integration protocol',encoding='utf-8')
    validation=experiment(store,'reference','aggregate',protocol)
    assert validation['acceptance']=='failed'
    assert not (store.path('reference')/'normal-report.json').exists()
    assert replay_reference(store,'reference')['status']=='identical'
