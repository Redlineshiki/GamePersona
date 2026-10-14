"""Generate new versioned reports from saved inputs, without provider requests."""
import uuid
from psycopg.types.json import Jsonb
from ..storage import content_hash,utc_now


def recompute_saved_reports(db, engine, reference_id):
    engine.load(reference_id)
    updated=skipped=0
    with db.connect() as con:
        owners=con.execute("SELECT id FROM users WHERE NOT deleting ORDER BY id FOR UPDATE").fetchall()
        for owner in owners:
            user=owner['id']
            if con.execute("SELECT 1 FROM tasks WHERE user_id=%s AND state IN ('pending','running')",(user,)).fetchone():
                skipped+=1;continue
            source=con.execute("SELECT * FROM input_snapshots WHERE user_id=%s AND read_status IN ('success','explicit_empty') ORDER BY created_at DESC,id DESC LIMIT 1",(user,)).fetchone()
            if not source:
                skipped+=1;continue
            records=source['records'];input_hash=content_hash(records)
            if input_hash!=source['content_sha256']:
                raise ValueError('已保存的输入内容哈希不一致')
            existing=con.execute("SELECT 1 FROM reports WHERE user_id=%s AND payload->'versions'->>'reference'=%s AND payload->'collection'->>'input_sha256'=%s",
                                 (user,reference_id,input_hash)).fetchone()
            if existing:
                skipped+=1;continue
            old=con.execute('SELECT payload FROM reports WHERE user_id=%s AND input_id=%s ORDER BY created_at DESC LIMIT 1',
                            (user,source['id'])).fetchone()
            previous=old['payload'] if old else {}
            task_id,input_id,report_id=(uuid.uuid4().hex for _ in range(3))
            report=engine.assess(records,source['read_status'],reference_id,input_id)
            report['game_names']=previous.get('game_names',{})
            report['collection']={'collected_at':previous.get('collection',{}).get('collected_at',source['created_at'].isoformat()),
                'source':'saved Steam GetOwnedGames input','input_sha256':input_hash,'recomputed_at':utc_now()}
            report.pop('report_sha256',None);report['report_sha256']=content_hash(report)
            con.execute("INSERT INTO tasks(id,user_id,state,reference_id,read_status,report_id) VALUES(%s,%s,'succeeded',%s,%s,%s)",
                        (task_id,user,reference_id,source['read_status'],report_id))
            con.execute('INSERT INTO input_snapshots(id,user_id,task_id,read_status,records,content_sha256) VALUES(%s,%s,%s,%s,%s,%s)',
                        (input_id,user,task_id,source['read_status'],Jsonb(records),input_hash))
            con.execute('INSERT INTO reports(id,user_id,task_id,input_id,payload,report_sha256) VALUES(%s,%s,%s,%s,%s,%s)',
                        (report_id,user,task_id,input_id,Jsonb(report),report['report_sha256']))
            updated+=1
    return {'updated_reports':updated,'skipped_users':skipped,'reference':reference_id}
