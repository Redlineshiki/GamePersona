from contextlib import asynccontextmanager
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, load_settings
from .db import Database
from .auth import SteamOpenID, token_hash
from .worker import AssessmentEngine, Worker, collect_games
from ..storage import Store
from ..interpretation import share_projection

COOKIE = 'gamepersona_session'
LOGIN_COOKIE = 'gamepersona_login'


def create_app(settings: Settings | None = None, verifier=None, collector=collect_games, engine=None):
    settings = settings or load_settings()
    cookie_name = COOKIE+'_'+token_hash(settings.origin)[:8]
    login_cookie_name = LOGIN_COOKIE+'_'+token_hash(settings.origin)[:8]
    db = Database(settings.database_url)
    db.migrate()
    engine = engine or AssessmentEngine(Store(settings.root))
    if engine:
        engine.load(settings.reference)
    verifier = verifier or SteamOpenID(db)
    worker = Worker(db,settings,engine,collector)

    @asynccontextmanager
    async def lifespan(app):
        if settings.worker_enabled:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.db,app.state.worker,app.state.settings = db,worker,settings
    app.state.cookie_name,app.state.login_cookie_name = cookie_name,login_cookie_name

    @app.middleware('http')
    async def private_headers(request,call_next):
        if request.headers.get('host') != urlsplit(settings.origin).netloc:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'站点地址不匹配'},status_code=400)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; font-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://steamcommunity.com"
        return response

    def session(request: Request):
        token = request.cookies.get(cookie_name,'')
        with db.connect() as con:
            result = con.execute('SELECT s.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE token_hash=%s AND expires_at>now() AND NOT u.deleting',(token_hash(token),)).fetchone()
        if not result:
            raise HTTPException(401,'请先通过 Steam 登录')
        return result

    def mutation(request: Request):
        s = session(request)
        if request.headers.get('origin')!=settings.origin or not secrets.compare_digest(request.headers.get('x-csrf-token',''),s['csrf']):
            raise HTTPException(403,'请求验证失败，请刷新页面重试')
        return s

    @app.get('/api/session')
    def get_session(request: Request):
        try:
            s = session(request)
            return {'authenticated':True,'csrf':s['csrf'],'expires_at':s['expires_at'].isoformat()}
        except HTTPException:
            return {'authenticated':False}

    @app.get('/auth/steam')
    def start_login(request: Request):
        state,binding = secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        return_to = settings.origin+'/auth/callback?state='+state
        try:
            owner = session(request)['user_id']
        except HTTPException:
            owner = None
        with db.connect() as con:
            con.execute('DELETE FROM login_transactions WHERE expires_at<now()')
            con.execute("INSERT INTO login_transactions(state_hash,binding_hash,user_id,return_to,expires_at) VALUES(%s,%s,%s,%s,now()+interval '10 minutes')",(token_hash(state),token_hash(binding),owner,return_to))
        response = RedirectResponse(verifier.login_url(settings.origin,return_to),status_code=303)
        response.set_cookie(login_cookie_name,binding,max_age=600,httponly=True,samesite='lax',secure=settings.secure)
        return response

    @app.get('/auth/callback')
    def callback(request: Request):
        # Duplicate fields are rejected rather than interpreted inconsistently.
        pairs = list(request.query_params.multi_items())
        parameters = dict(pairs)
        if len(pairs)!=len(parameters):
            raise HTTPException(400,'登录返回参数无效')
        with db.connect() as con:
            transaction = con.execute("UPDATE login_transactions SET consumed=true WHERE state_hash=%s AND binding_hash=%s AND NOT consumed AND expires_at>now() RETURNING *",
                (token_hash(parameters.get('state','')),token_hash(request.cookies.get(login_cookie_name,'')))).fetchone()
        if not transaction:
            raise HTTPException(400,'登录已过期或已使用，请重新登录')
        steam_id = verifier.verify(parameters,transaction['return_to'])
        if not steam_id:
            return RedirectResponse('/?login=failed',status_code=303)
        token,csrf = secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        with db.connect() as con:
            if transaction['user_id'] and not con.execute('SELECT id FROM users WHERE id=%s AND NOT deleting FOR UPDATE',(transaction['user_id'],)).fetchone():
                raise HTTPException(400,'账号关联已删除，请重新开始登录')
            owner = con.execute('INSERT INTO users(id,steam_id) VALUES(%s,%s) ON CONFLICT(steam_id) DO UPDATE SET steam_id=EXCLUDED.steam_id RETURNING id',(uuid.uuid4().hex,steam_id)).fetchone()['id']
            con.execute('DELETE FROM sessions WHERE token_hash=%s',(token_hash(request.cookies.get(cookie_name,'')),))
            con.execute("INSERT INTO sessions VALUES(%s,%s,%s,now()+interval '12 hours')",(token_hash(token),owner,csrf))
            con.execute('DELETE FROM login_transactions WHERE state_hash=%s',(transaction['state_hash'],))
        response = RedirectResponse('/',status_code=303)
        response.set_cookie(cookie_name,token,max_age=43200,httponly=True,samesite='lax',secure=settings.secure)
        response.delete_cookie(login_cookie_name)
        return response

    @app.post('/api/logout')
    def logout(request: Request):
        s = mutation(request)
        with db.connect() as con:
            con.execute('DELETE FROM sessions WHERE token_hash=%s',(s['token_hash'],))
        from fastapi.responses import JSONResponse
        response = JSONResponse({'status':'logged_out'})
        response.delete_cookie(cookie_name)
        return response

    @app.delete('/api/account')
    def delete_account(request: Request):
        s = mutation(request)
        with db.connect() as con:
            con.execute('SELECT id FROM users WHERE id=%s FOR UPDATE',(s['user_id'],))
            con.execute('UPDATE users SET deleting=true WHERE id=%s',(s['user_id'],))
            con.execute('DELETE FROM users WHERE id=%s',(s['user_id'],))
        from fastapi.responses import JSONResponse
        response = JSONResponse({'status':'deleted','scope':'网站身份关联、会话、任务、输入与报告；浏览器 PNG 和旧 CLI 快照需单独删除。'})
        response.delete_cookie(cookie_name)
        response.delete_cookie(login_cookie_name)
        return response

    @app.post('/api/assessments',status_code=202)
    def assessment(request: Request):
        s = mutation(request)
        if not settings.steam_api_key:
            raise HTTPException(503,'服务器尚未配置 Steam API Key')
        with db.connect() as con:
            owner = con.execute('SELECT id FROM users WHERE id=%s AND NOT deleting FOR UPDATE',(s['user_id'],)).fetchone()
            if not owner:
                raise HTTPException(401,'账号已删除')
            task = con.execute("SELECT id FROM tasks WHERE user_id=%s AND state IN ('pending','running')",(s['user_id'],)).fetchone()
            if task:
                return {'task_id':task['id']}
            if con.execute("SELECT id FROM tasks WHERE user_id=%s AND created_at>now()-interval '30 seconds'",(s['user_id'],)).fetchone():
                raise HTTPException(429,'请稍候再重新读取')
            task_id = uuid.uuid4().hex
            con.execute("INSERT INTO tasks(id,user_id,state,reference_id) VALUES(%s,%s,'pending',%s)",(task_id,s['user_id'],settings.reference))
        return {'task_id':task_id}

    @app.get('/api/tasks/{task_id}')
    def get_task(task_id: str,request: Request):
        s = session(request)
        with db.connect() as con:
            result = con.execute('SELECT id,state,read_status,report_id,error_code FROM tasks WHERE id=%s AND user_id=%s',(task_id,s['user_id'])).fetchone()
        if not result:
            raise HTTPException(404,'任务不存在')
        return result

    @app.get('/api/reports')
    def list_reports(request: Request):
        s = session(request)
        with db.connect() as con:
            return con.execute('SELECT id,created_at,report_sha256 FROM reports WHERE user_id=%s ORDER BY created_at DESC LIMIT 100',(s['user_id'],)).fetchall()

    def owned_report(report_id,request):
        s = session(request)
        with db.connect() as con:
            row = con.execute('SELECT payload FROM reports WHERE id=%s AND user_id=%s',(report_id,s['user_id'])).fetchone()
        if not row:
            raise HTTPException(404,'报告不存在')
        return row['payload']

    @app.get('/api/reports/{report_id}')
    def get_report(report_id: str,request: Request):
        return owned_report(report_id,request)

    @app.get('/api/reports/{report_id}/share')
    def share(report_id: str,request: Request):
        return share_projection(owned_report(report_id,request))

    static = Path(__file__).resolve().parents[2]/'web'/'dist'
    if static.exists():
        app.mount('/assets',StaticFiles(directory=static/'assets'),name='assets')
        @app.get('/')
        def home():
            return FileResponse(static/'index.html')
    else:
        @app.get('/')
        def home():
            return {'detail':'请先在 web 目录运行 npm run build'}
    return app
