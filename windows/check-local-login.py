"""Reproduce a same-PC ss.info login with a listener that excludes 127.0.0.1."""
import argparse
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--expect-broken', action='store_true')
args = parser.parse_args()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
address = '127.0.0.2'  # Same machine, but the listener does not accept 127.0.0.1.
with socket.socket() as probe:
    probe.bind((address, 0))
    port = probe.getsockname()[1]
with tempfile.TemporaryDirectory(prefix='bbsc-local-login-') as temp:
    folder = Path(temp)
    env = dict(os.environ, PYTHONUTF8='1')
    with (folder / 'server.log').open('wb') as log:
        process = subprocess.Popen([
            sys.executable, '-B', '-u', str(ROOT / 'bbsc-game/bbsc_gameserver.py'),
            '--host', address, '--advertise', address, '--port', str(port), '--relay-port', '0',
            '--shadnet', address, '--shadnet-webapi', f'http://{address}:31415',
            '--no-bbhost', '--no-playlog', '--summon-interval', '2', '--log-dir', str(folder), '--data', str(folder / 'data.json')],
            env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(80):
                if process.poll() is not None:
                    raise AssertionError('Isolated game service exited')
                try:
                    with opener.open(f'http://{address}:{port}/bb-eu/ss.info', timeout=0.5) as reply:
                        xml = base64.b64decode(reply.read()).decode()
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError('Isolated game service not ready')
            doc = ET.fromstring('<root>' + xml + '</root>')
            for tag in ('SummonDataGetListInterval2', 'SummonDataCreateInterval2'):
                assert [e.text for e in doc.iter(tag)] == ['2'], tag
            login = next(e.text for e in doc.iter() if e.tag == 'api_Login')
            if args.expect_broken:
                assert login == f'http://127.0.0.1:{port}', login
                try:
                    opener.open(login, timeout=0.5)
                except OSError:
                    print('REPRODUCED: same-PC ss.info advertises an unbound loopback login address')
                else:
                    raise AssertionError('Expected the advertised login address to be unreachable')
            else:
                assert login == f'http://{address}:{port}', login
                request = urllib.request.Request(login + '/basic_utils/login', data=b'{"MessageId":"LoginRequest"}',
                                                 headers={'Content-Type': 'application/json'})
                with opener.open(request, timeout=2) as reply:
                    result = json.load(reply)
                assert result['ResKind'] == 0 and result['MessageId'] == 'LoginResponse'
                summons = [e.text for e in doc.iter() if e.tag.startswith('api_SummonData')]
                assert summons and all(url.startswith(f'http://{address}:31415') for url in summons)
                print('PASS: same-PC advertised login is reachable; login and summon endpoints correct')
        finally:
            process.terminate()
            process.wait(timeout=10)
