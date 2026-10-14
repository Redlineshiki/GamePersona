import threading
import time
import uuid

import httpx
from psycopg.types.json import Jsonb

from ..collect import Fetcher, STEAM_URL, classify_steam, normalize_steam
from ..scoring import score_records, feature_index
from ..reference import build_report
from ..storage import Store, read_json, content_hash, utc_now


class AssessmentEngine:
    def __init__(self, store: Store):
        self.store = store
        self.cache = {}

    def load(self, reference_id):
        if reference_id not in self.cache:
            manifest = self.store.load(reference_id,'reference')
            if manifest.get('experimental_acceptance')!='passed':
                raise ValueError('参考实验未通过，不能开放正式测评')
            self.store.verify(reference_id)
            path = self.store.path(reference_id)
            loaded = (read_json(path/'model.json'),read_json(path/'reference.json'),feature_index(read_json(path/'features.json')))
            model,reference,_ = loaded
            if reference.get('version') == 'stage3-reference-weight-v1':
                from ..weight_reference import validate_weight_reference
                validate_weight_reference(reference,model,full=True)
            self.cache[reference_id] = loaded
        return self.cache[reference_id]

    def assess(self, records, read_status, reference_id, input_id):
        model,ref,features = self.load(reference_id)
        return build_report(score_records(records,features,model,read_status),ref,model,input_id)


def collect_games(api_key, steam_id):
    with httpx.Client(follow_redirects=False) as client:
        result = Fetcher(client).get(STEAM_URL,{'key':api_key,'steamid':steam_id,'include_appinfo':1,'include_played_free_games':1})
    return classify_steam(result['response']) if result['status']=='ok' else (result['status'],[])


class Worker:
    def __init__(self,db,settings,engine,collector=collect_games):
        self.db,self.settings,self.engine,self.collector = db,settings,engine,collector
        self.stop_event = threading.Event()
        self.thread = None

    def run_once(self):
        with self.db.connect() as con:
            task = con.execute("SELECT t.*,u.steam_id FROM tasks t JOIN users u ON u.id=t.user_id WHERE t.state='pending' AND NOT u.deleting ORDER BY t.created_at FOR UPDATE OF t SKIP LOCKED LIMIT 1").fetchone()
            if not task:
                return False
            con.execute("UPDATE tasks SET state='running' WHERE id=%s",(task['id'],))
        try:
            status,games = self.collector(self.settings.steam_api_key,task['steam_id'])
            records = normalize_steam(games,task['id']) if status in {'success','explicit_empty'} else []
            input_id,report_id = uuid.uuid4().hex,uuid.uuid4().hex
            report = self.engine.assess(records,status,task['reference_id'],input_id) if status in {'success','explicit_empty'} else None
            if report:
                report['game_names'] = {str(g['appid']):g['name'] for g in games
                                        if type(g.get('appid')) is int and isinstance(g.get('name'),str)}
                report['collection'] = {'collected_at':utc_now(),'source':'Steam GetOwnedGames',
                                        'input_sha256':content_hash(records)}
                report.pop('report_sha256',None)
                report['report_sha256'] = content_hash(report)
            with self.db.connect() as con:
                # Serializes completion against account deletion and checks the task
                # still exists before writing any new private data.
                owner = con.execute('SELECT id FROM users WHERE id=%s AND NOT deleting FOR UPDATE',(task['user_id'],)).fetchone()
                current = con.execute("SELECT id FROM tasks WHERE id=%s AND state='running'",(task['id'],)).fetchone()
                if not owner or not current:
                    return True
                if report is None:
                    con.execute("UPDATE tasks SET state='failed',read_status=%s,error_code=%s WHERE id=%s",(status,status,task['id']))
                else:
                    con.execute('INSERT INTO input_snapshots(id,user_id,task_id,read_status,records,content_sha256) VALUES(%s,%s,%s,%s,%s,%s)',
                        (input_id,task['user_id'],task['id'],status,Jsonb(records),content_hash(records)))
                    con.execute('INSERT INTO reports(id,user_id,task_id,input_id,payload,report_sha256) VALUES(%s,%s,%s,%s,%s,%s)',
                        (report_id,task['user_id'],task['id'],input_id,Jsonb(report),report['report_sha256']))
                    con.execute("UPDATE tasks SET state='succeeded',read_status=%s,report_id=%s WHERE id=%s",(status,report_id,task['id']))
        except Exception:
            # Do not return provider URLs, credentials, account IDs or raw exceptions.
            with self.db.connect() as con:
                con.execute("UPDATE tasks SET state='failed',error_code='assessment_failed' WHERE id=%s AND state='running'",(task['id'],))
        return True

    def _loop(self):
        import psycopg
        # Only one worker may recover/execute tasks for this database at a time.
        while not self.stop_event.is_set():
            try:
                with self.db.connect() as leader:
                    leader.autocommit = True
                    if not leader.execute('SELECT pg_try_advisory_lock(hashtext(current_schema()),53170002) locked').fetchone()['locked']:
                        self.stop_event.wait(1)
                        continue
                    with self.db.connect() as con:
                        con.execute("UPDATE tasks SET state='pending' WHERE state='running'")
                    while not self.stop_event.is_set():
                        if not self.run_once():
                            self.stop_event.wait(.5)
            except psycopg.Error:
                # A temporary database outage must not leave future tasks waiting
                # forever after the service becomes available again.
                self.stop_event.wait(1)

    def start(self):
        self.thread = threading.Thread(target=self._loop,daemon=True,name='gamepersona-worker')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
