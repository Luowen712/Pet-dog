"""Windows local SIM: a separate loopback MySQL 8 instance; never reads the configured DB_URL."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time

import pymysql

BACKEND = Path(__file__).resolve().parent
HOME = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'PetDog' / 'sim-v1'
PORT = 33317
DB = 'pet_dog_sim'


async def serve_sim(stop):
    import uvicorn
    from app.main import app
    app.state.host_lock_path = HOME / 'sim-host.lock'
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8000,
                            access_log=False, ws_ping_interval=20, ws_ping_timeout=10))
    async def watch_stop():
        while not stop.exists():
            await asyncio.sleep(.5)
        server.should_exit = True
    watcher = asyncio.create_task(watch_stop())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def main():
    stop = HOME / 'stop.request'
    if sys.argv[1:] == ['--stop']:
        if HOME.is_dir():
            stop.touch()
        return
    if sys.argv[1:]:
        raise SystemExit('Usage: run_sim.py [--stop]')
    program = shutil.which('mysqld') or str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'MySQL/MySQL Server 8.0/bin/mysqld.exe')
    if not Path(program).is_file():
        raise SystemExit('Local SIM requires MySQL Server 8.0 (mysqld on PATH).')
    for port in (PORT, 8000):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise SystemExit(f'Port {port} already in use; no changes made.')
    os.chdir(BACKEND)
    HOME.mkdir(parents=True, exist_ok=True)
    stop.unlink(missing_ok=True)
    data = HOME / 'mysql'
    config = HOME / 'private.json'
    demo = HOME / 'login.txt'
    init = HOME / 'first-start.sql'
    if not config.exists():
        if data.exists():
            raise SystemExit('Existing SIM data without credentials. Refusing to reinitialize.')
        with config.open('x', encoding='ascii') as out:
            json.dump({k: secrets.token_hex(32) for k in ('root', 'app', 'jwt')}, out)
    keys = json.loads(config.read_text(encoding='ascii'))
    args = [program, '--no-defaults', f'--datadir={data}', '--log-error=' + str(HOME / 'mysql.log')]
    if not data.exists():
        init.write_text(
            f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{keys['root']}';\n"
            f"CREATE DATABASE {DB} CHARACTER SET utf8mb4;\n"
            f"CREATE USER 'petdog'@'127.0.0.1' IDENTIFIED BY '{keys['app']}';\n"
            f"GRANT ALL ON {DB}.* TO 'petdog'@'127.0.0.1';\n", encoding='ascii')
        subprocess.run([*args, '--initialize-insecure'], check=True)
    args += ['--bind-address=127.0.0.1', f'--port={PORT}', '--mysqlx=OFF', '--skip-log-bin', '--innodb-buffer-pool-size=64M']
    if init.exists():
        args += ['--init-file=' + str(init)]
    server = subprocess.Popen(args, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    control = None
    try:
        for _ in range(120):
            if server.poll() is not None:
                raise RuntimeError(f'SIM MySQL exited. See {HOME / "mysql.log"}')
            try:
                control = pymysql.connect(host='127.0.0.1', port=PORT, user='root', password=keys['root'], connect_timeout=1)
                break
            except pymysql.OperationalError:
                time.sleep(.25)
        if control is None:
            raise RuntimeError('SIM MySQL did not start.')
        with control.cursor() as cur:
            cur.execute('SELECT @@datadir')
            if Path(cur.fetchone()[0]).resolve() != data.resolve():
                control.close()
                control = None
                raise RuntimeError('Unexpected MySQL instance; refusing to use it.')
        init.unlink(missing_ok=True)
        os.environ.update(DB_URL=f"mysql+pymysql://petdog:{keys['app']}@127.0.0.1:{PORT}/{DB}?charset=utf8mb4",
                          JWT_SECRET=keys['jwt'], SERIAL_PORT='sim', DEV_HEARTBEAT='false')
        from alembic import command
        from alembic.config import Config
        from app.db import SessionLocal
        from app.link.ble_link import SIM_BLE_ADDRESS, SIM_BLE_NAME
        from app.models import Device, User
        from app.security import hash_pwd
        from app.config import settings
        # The simulated transport never opens the configured physical port or picks a production device.
        command.upgrade(Config('alembic.ini'), 'head')
        with SessionLocal.begin() as db:
            if not db.query(User.id).first() and not db.query(Device.id).first():
                password = secrets.token_urlsafe(15)
                user = User(username='simulator', password_hash=hash_pwd(password), role='admin', status='active')
                db.add(user)
                db.flush()
                db.add(Device(device_id=SIM_BLE_ADDRESS, name=SIM_BLE_NAME, status='bound', be=1, owner_id=user.id, handover_state='ready'))
                demo.write_text(f'Username: simulator\nPassword: {password}\n', encoding='ascii')
        with SessionLocal() as db:
            settings.SERIAL_DEVICE_PK = db.query(Device.id).filter(Device.device_id.in_((SIM_BLE_ADDRESS, 'LOCAL-SIM'))).scalar()
            if settings.SERIAL_DEVICE_PK is None:
                raise RuntimeError('Simulated BLE device is not registered in the demonstration database.')
        print(f'Local SIM login: {demo}', flush=True)
        asyncio.run(serve_sim(stop))
    finally:
        if control is not None:
            try:
                with control.cursor() as cur:
                    cur.execute('SHUTDOWN')
            except pymysql.MySQLError:
                pass
            control.close()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.terminate()
            server.wait(timeout=10)


if __name__ == '__main__':
    main()
