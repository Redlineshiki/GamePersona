"""Workspace-only PostgreSQL bootstrap; no installer, service registration, or public listener."""
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlsplit
import hashlib
import secrets
import subprocess
import zipfile
import argparse

URL='https://get.enterprisedb.com/postgresql/postgresql-18.6-5-windows-x64-binaries.zip'
SHA256='e2246ba91d22345bc3d017586c09ede52d9df180b1eeb480f050445f1cad84e2'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['start','stop','status'])
    args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent
    cache=root/'.cache';cache.mkdir(exist_ok=True)
    archive=cache/'postgresql-18.6.zip';binary=cache/'postgresql'/'pgsql'/'bin'
    data=cache/'postgres-data';env=root/'.env.web'
    if args.command!='start':
        return subprocess.run([str(binary/'pg_ctl.exe'),args.command,'-D',str(data)]).returncode
    if not binary.exists():
        if not archive.exists():
            print('Downloading official PostgreSQL 18.6 portable binaries (~385 MB).',flush=True)
            with urlopen(URL,timeout=60) as response,archive.open('wb') as output:
                while chunk:=response.read(1024*1024):output.write(chunk)
        with archive.open('rb') as source:
            if hashlib.file_digest(source,'sha256').hexdigest()!=SHA256:
                raise ValueError('PostgreSQL archive checksum mismatch; remove the incomplete archive and retry')
        extraction=(cache/'postgresql').resolve()
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                if item.filename.startswith(('pgsql/bin/','pgsql/lib/','pgsql/share/')):
                    if not (extraction/item.filename).resolve().is_relative_to(extraction):
                        raise ValueError('Unsafe archive path')
                    source.extract(item,extraction)
    if not env.exists():
        password=secrets.token_urlsafe(32)
        env.write_text('DATABASE_URL=postgresql://gamepersona:'+password+'@127.0.0.1:55432/gamepersona\nGAMEPERSONA_ORIGIN=http://127.0.0.1:8000\nGAMEPERSONA_REFERENCE=stage3-reference-v1-20261014\n',encoding='utf-8')
    values=dict(line.split('=',1) for line in env.read_text(encoding='utf-8').splitlines() if '=' in line and not line.startswith('#'))
    dsn=values['DATABASE_URL']
    url=urlsplit(dsn)
    if url.hostname!='127.0.0.1' or url.port!=55432 or url.username!='gamepersona':
        raise ValueError('Bootstrap supports only the local workspace PostgreSQL configuration')
    if not (data/'PG_VERSION').exists():
        password_file=cache/'postgres-password'
        try:
            password_file.write_text(url.password,encoding='utf-8')
            subprocess.run([str(binary/'initdb.exe'),'-D',str(data),'-U','gamepersona','--auth=scram-sha-256',
                            '--pwfile',str(password_file),'--encoding=UTF8','--locale=C'],check=True)
        finally:
            password_file.unlink(missing_ok=True)
    status=subprocess.run([str(binary/'pg_ctl.exe'),'status','-D',str(data)],capture_output=True)
    if status.returncode:
        # pg_ctl detaches the server, which logs to this project-owned file.
        subprocess.run([str(binary/'pg_ctl.exe'),'start','-D',str(data),'-l',str(cache/'postgres.log'),
                        '-o','-h 127.0.0.1 -p 55432','-w'],check=True)
    import psycopg
    with psycopg.connect(dsn.rsplit('/',1)[0]+'/postgres',autocommit=True) as con:
        if not con.execute("SELECT 1 FROM pg_database WHERE datname='gamepersona'").fetchone():con.execute('CREATE DATABASE gamepersona')
    print('Local PostgreSQL ready at 127.0.0.1:55432; credentials remain in .env.web.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
