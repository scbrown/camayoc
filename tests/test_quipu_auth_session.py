"""Real subprocess/session boundaries with fake servers and private homes."""
import os
import unittest
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scripts import quipu_auth



def test_real_registry_401_once_across_subprocesses(tmp_path):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            seen.append(self.path)
            self.send_response(200 if self.path == "/query" else 401)
            self.end_headers()
            self.wfile.write(b'{"rows": []}' if self.path == "/query" else b'fixture-response-secret')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    env = dict(os.environ, HOME=str(tmp_path), XDG_STATE_HOME=str(tmp_path / 'state'),
               QUIPU_AUTH_TOKEN='fixture-token', QUIPU_SESSION='fixture-one')
    code = '''
import sys
from scripts import planes
try:
    planes.SERVER = sys.argv[1]
    planes.AUTH = None
    planes._post('/knot', {}, client='camayoc-planes')
except Exception as error:
    print(type(error).__name__)
'''
    def run(endpoint=url):
        return subprocess.run([sys.executable, '-c', code, endpoint], env=env,
                              capture_output=True, text=True, timeout=10)
    try:
        results = [run() for _ in range(3)]
        assert seen == ['/knot']
        assert sum('camayoc: Quipu credential' in r.stderr for r in results) == 1
        assert all('fixture-response-secret' not in r.stderr + r.stdout for r in results)
        env['QUIPU_SESSION'] = 'fixture-two'
        assert run().returncode == 0
        assert len(seen) == 2
        assert run(url + '/other').returncode == 0
        assert len(seen) == 3
        env['QUIPU_SESSION'] = 'fixture-missing'
        env['QUIPU_AUTH_TOKEN'] = ''
        env['QUIPU_AUTH_TOKEN_FILE'] = str(tmp_path / 'absent')
        missing = [run() for _ in range(3)]
        assert len(seen) == 3
        assert sum('camayoc: Quipu credential' in r.stderr for r in missing) == 1
        assert all('PlaneError' in r.stdout for r in missing)
        read = subprocess.run([sys.executable, '-c',
            "from scripts import planes; import sys; planes.SERVER=sys.argv[1]; planes.AUTH=None; planes._post('/query', {}, client='fixture-read')", url],
            env=env, capture_output=True, text=True, timeout=10)
        assert read.returncode == 0, read.stderr
        assert seen[-1] == '/query'
        markers = list((tmp_path / 'state/camayoc/quipu-auth').glob('*.disabled'))
        assert len(markers) == 4
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in markers)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()



class SessionTransportTests(unittest.TestCase):
    def test_subprocess_refusal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            test_real_registry_401_once_across_subprocesses(Path(home))

    def test_resolution_shared_by_planes_and_rml(self):
        import tempfile
        from unittest.mock import patch
        from scripts import planes, rml_executor
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}, clear=True), patch.object(planes, 'AUTH', None):
            canonical = Path(home) / '.config/quipu/token'
            legacy = Path(home) / '.config/aegis/quipu_token'
            legacy.parent.mkdir(parents=True)
            legacy.write_text('legacy')
            self.assertIsNone(planes.auth_token())
            self.assertIsNone(rml_executor.auth_token())
            canonical.parent.mkdir(parents=True)
            canonical.write_text('canonical\n')
            self.assertEqual(planes.auth_token(), 'canonical')
            self.assertEqual(rml_executor.auth_token(), 'canonical')
            os.environ['QUIPU_AUTH_TOKEN_FILE'] = str(legacy)
            self.assertEqual(rml_executor.auth_token(), 'legacy')
            os.environ['QUIPU_AUTH_TOKEN'] = '  inline \n'
            self.assertEqual(planes.auth_token(), 'inline')
            self.assertEqual(rml_executor.auth_token(), 'inline')
            os.environ['QUIPU_AUTH_TOKEN'] = ' \n'
            os.environ['QUIPU_AUTH_TOKEN_FILE'] = str(Path(home) / 'absent')
            self.assertIsNone(planes.auth_token())
            self.assertIsNone(rml_executor.auth_token())

    def test_rml_cli_latches_unreadable_and_invalid_credentials(self):
        import tempfile
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                seen.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"conforms":true,"tx_id":42,"count":4}')
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        root=Path(__file__).resolve().parents[1]
        args=[sys.executable,str(root/'scripts/rml_executor.py'),'execute',
              'https://example.invalid/rml/map','--mapping-file',str(root/'tests/fixtures/rml/valid.ttl'),
              '--source-file',str(root/'tests/fixtures/rml/records.json'),
              '--server',f'http://127.0.0.1:{server.server_port}','--actor','fixture']
        try:
            for kind in ['unreadable','invalid']:
                with self.subTest(kind=kind),tempfile.TemporaryDirectory() as home:
                    env=dict(os.environ,HOME=home,XDG_STATE_HOME=home+'/state',
                             QUIPU_SESSION='rml-'+kind,QUIPU_AUTH_TOKEN='')
                    unreadable=Path(home)/'directory-token';unreadable.mkdir()
                    env['QUIPU_AUTH_TOKEN_FILE']=str(unreadable)
                    if kind=='invalid':env['QUIPU_AUTH_TOKEN']='private-fixture\ninjected-header'
                    before=len(seen)
                    first=subprocess.run(args,env=env,capture_output=True,text=True,timeout=10)
                    self.assertEqual(first.returncode,2,first.stdout+first.stderr)
                    self.assertEqual(len(seen),before)
                    self.assertEqual(first.stderr.count('camayoc: Quipu credential'),1)
                    self.assertNotIn('private-fixture',first.stdout+first.stderr)
                    self.assertEqual(len(list((Path(home)/'state/camayoc/quipu-auth').glob('*.disabled'))),1)
                    env['QUIPU_AUTH_TOKEN']='isolated-test-fixture'
                    same=subprocess.run(args,env=env,capture_output=True,text=True,timeout=10)
                    self.assertEqual(same.returncode,2,same.stdout+same.stderr)
                    self.assertEqual(len(seen),before)
                    self.assertNotIn('camayoc: Quipu credential',same.stderr)
                    env['QUIPU_SESSION']='new-rml-'+kind
                    fresh=subprocess.run(args,env=env,capture_output=True,text=True,timeout=10)
                    self.assertEqual(fresh.returncode,0,fresh.stdout+fresh.stderr)
                    self.assertEqual(len(seen),before+1)
        finally:
            server.shutdown();server.server_close();thread.join()
