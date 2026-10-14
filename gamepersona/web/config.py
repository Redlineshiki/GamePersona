from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    database_url: str
    origin: str = 'http://127.0.0.1:8000'
    reference: str = 'stage3-reference-weight-v3-20261014'
    root: Path = Path('artifacts')
    steam_api_key: str = ''
    worker_enabled: bool = True

    def __post_init__(self):
        u = urlsplit(self.origin)
        if u.scheme not in {'http','https'} or not u.netloc or u.path or u.query or u.fragment or u.username:
            raise ValueError('站点 origin 配置无效')
        if u.scheme == 'http' and u.hostname not in {'127.0.0.1','localhost','::1'}:
            raise ValueError('公网站点必须使用 HTTPS')

    @property
    def secure(self):
        return self.origin.startswith('https:')


def load_settings() -> Settings:
    values = {}
    for name in ('.env','.env.web'):
        p = Path(name)
        if p.exists():
            for line in p.read_text(encoding='utf-8-sig').splitlines():
                key,sep,value = line.partition('=')
                if sep and not key.startswith('#'):
                    values[key.strip()] = value.strip().strip('\"\'')
    def get(key, default=''):
        return os.environ.get(key,values.get(key,default))
    dsn = get('DATABASE_URL')
    if not dsn:
        raise ValueError('请配置本地 DATABASE_URL；不要把凭据发送到聊天中')
    return Settings(dsn, get('GAMEPERSONA_ORIGIN','http://127.0.0.1:8000'),
                    get('GAMEPERSONA_REFERENCE','stage3-reference-weight-v3-20261014'),
                    Path(get('GAMEPERSONA_ROOT','artifacts')),get('STEAM_API_KEY'))
