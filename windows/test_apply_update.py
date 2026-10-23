"""Exercise the actual detached installer against disposable installs, never game data."""
import hashlib
import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
HELPER = next((path for path in (HERE / 'Apply-Update.ps1', HERE.parent / 'launcher/Apply-Update.ps1',
                                HERE / 'package-src/Apply-Update.ps1') if path.is_file()), HERE / 'Apply-Update.ps1')
POWERSHELL = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


def sha(data):
    return hashlib.sha256(data).hexdigest()


@unittest.skipUnless(os.name == 'nt', 'Windows installer tests')
class AutomaticUpdate(unittest.TestCase):
    def fixture(self, client=False, extra=None):
        parent = HERE / 'installer-tests'
        parent.mkdir(exist_ok=True)
        area = Path(tempfile.mkdtemp(prefix='case-', dir=parent))
        root = area / 'installed'; root.mkdir()
        entry = 'BBSC-Launcher.exe' if client else 'Server.exe'
        private = ({'.private/account.clixml': b'private-credential-marker',
                    'data/user/savedata/userdata0000': b'private-save-marker',
                    'profile.json': b'private-profile-marker',
                    'features.json': b'private-feature-marker',
                    'mod/guest-items/a.json': b'private-guest-marker',
                    'mod/own-world/a.json': b'private-world-marker'} if client else {
                    'normal/db/shadnet.db': b'normal-account-marker',
                    'bbsc/db/shadnet.db': b'bbsc-account-marker',
                    'bbsc/online-data.json': b'private-online-marker',
                    'normal/shadnet.cfg': b'private-network-marker',
                    'server.json': b'{"address":"100.64.1.2"}',
                    'normal/worlds.cfg': b'private-world-config-marker'})
        private['update-settings.json'] = b'private-update-options-marker'
        old = {entry: b'old-entry', 'a.txt': b'old-a', 'z.dll': b'old-z', **private}
        for name, data in old.items():
            target = root / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        files = {entry: b'new-entry', 'a.txt': b'new-a', 'z.dll': b'new-z',
                 'Apply-Update.ps1': HELPER.read_bytes()}
        if not client:
            files.update({'server.json': b'{"address":"127.0.0.1"}', 'normal/worlds.cfg': b'new-world-default'})
        files.update(extra or {})
        if client:
            files['BUILD-INFO.json'] = json.dumps({'version': '0.2.0-preview.1'}).encode()
            files['file-sha256.json'] = json.dumps({name: sha(data) for name, data in files.items()}).encode()
        else:
            files['BUILD-INFO.json'] = json.dumps({'label': '0.2.0-preview.1',
                'files': {name: sha(data) for name, data in files.items()}}).encode()
        archive = area / 'update.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name, data in files.items():
                bundle.writestr('Application/' + name, data)
        request = {'repository': 'TheHuntLauncher' if client else 'TheHuntServer',
                   'root': str(root), 'archive': str(archive), 'sha256': sha(archive.read_bytes()),
                   'version': '0.2.0-preview.1', 'parent_pid': 0}
        plan = area / 'plan.json'; plan.write_text(json.dumps(request), encoding='utf-8')
        return root, private, old, plan, request

    def run_installer(self, plan):
        return subprocess.run([str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(HELPER), '-Plan', str(plan), '-Headless', '-NoRestart'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

    def test_both_projects_replace_only_programs_and_keep_private_bytes(self):
        for client in (False, True):
            with self.subTest(client=client):
                root, private, old, plan, _ = self.fixture(client)
                result = self.run_installer(plan)
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])
                self.assertEqual((root / 'a.txt').read_bytes(), b'new-a')
                for name, data in private.items():
                    self.assertEqual((root / name).read_bytes(), data, name)
                backup = next((root / 'update-backups').iterdir())
                self.assertEqual((backup / 'program/a.txt').read_bytes(), b'old-a')
                self.assertTrue(json.loads((backup / 'result.json').read_text())['success'])
                self.assertFalse((backup / 'program/update-settings.json').exists())

    def test_locked_target_rolls_back_previously_replaced_files(self):
        root, private, old, plan, _ = self.fixture()
        with (root / 'z.dll').open('rb'):
            result = self.run_installer(plan)
        self.assertNotEqual(result.returncode, 0)
        for name, data in old.items():
            self.assertEqual((root / name).read_bytes(), data, name)
        backup = next((root / 'update-backups').iterdir())
        report = json.loads((backup / 'result.json').read_text())
        self.assertFalse(report['success'])
        self.assertIsNone(report['rollback_error'])
        self.assertIn('a.txt', report['applied'])

    def test_private_and_traversal_payloads_are_rejected_before_install(self):
        for name in ('../escape.txt', 'profile.json', 'bbport.ini', 'input.ini', 'mods.json', 'mod/guest-items/pickup.json', 'bbsc/db/shadnet.db', 'bbsc/online-data.json'):
            with self.subTest(name=name):
                root, _, old, plan, _ = self.fixture(extra={name: b'not-allowed'})
                result = self.run_installer(plan)
                self.assertNotEqual(result.returncode, 0)
                for path, data in old.items():
                    self.assertEqual((root / path).read_bytes(), data, path)
                self.assertFalse((root / 'update-backups').exists())

    def test_archive_hash_mismatch_never_replaces_files(self):
        root, _, old, plan, request = self.fixture()
        request['sha256'] = '0' * 64; plan.write_text(json.dumps(request), encoding='utf-8')
        self.assertNotEqual(self.run_installer(plan).returncode, 0)
        for name, data in old.items():
            self.assertEqual((root / name).read_bytes(), data)

    def test_running_application_mutex_blocks_installation(self):
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.GetFullPathNameW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPWSTR, ctypes.c_void_p)
        kernel.GetFullPathNameW.restype = wintypes.DWORD
        for client in (False, True):
            root, _, old, plan, _ = self.fixture(client)
            # Match .NET GetFullPath even when MSYS2 Python emits forward slashes.
            native_path = ctypes.create_unicode_buffer(32768)
            length = kernel.GetFullPathNameW(str(root), len(native_path), native_path, None)
            self.assertTrue(0 < length < len(native_path))
            native_root = native_path.value
            identity = native_root if client else native_root.lower() + '\\'
            digest = hashlib.sha256(identity.encode()).hexdigest().upper()
            name = ('Local\\BBSCLauncher-' + '-'.join(digest[i:i+2] for i in range(0, len(digest), 2))
                    if client else 'Local\\TheHuntServer-' + digest)
            handle = kernel.CreateMutexW(None, True, name)
            self.assertTrue(handle)
            try:
                installed = self.run_installer(plan)
                self.assertNotEqual(installed.returncode, 0,
                    'Application mutex was not respected: ' + repr((native_root, installed.stdout, installed.stderr)))
                for file, data in old.items():
                    self.assertEqual((root / file).read_bytes(), data, file)
            finally:
                kernel.ReleaseMutex(handle); kernel.CloseHandle(handle)

    def test_detached_helper_waits_for_parent_then_restarts_new_program(self):
        root, private, _, plan, request = self.fixture()
        area = plan.parent
        source = area / 'Stub.cs'
        source.write_text('using System; using System.IO; class Stub { static void Main() {'
            'var root=AppDomain.CurrentDomain.BaseDirectory;'
            'using(File.Open(Path.Combine(root,".update.lock"),FileMode.Open,FileAccess.Read,FileShare.None)) {}'
            'File.WriteAllText(Path.Combine(root,"restarted.txt"),"new program"); }}')
        executable = area / 'Stub.exe'
        compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        # Legacy csc interprets absolute POSIX-style paths as compiler switches.
        compiled = subprocess.run([str(compiler), '/nologo', '/target:winexe',
            '/out:Stub.exe', 'Stub.cs'], cwd=area, capture_output=True)
        self.assertEqual(compiled.returncode, 0, (compiled.stdout + compiled.stderr).decode(errors='replace'))
        archive = Path(request['archive'])
        with zipfile.ZipFile(archive) as bundle:
            files = {name: bundle.read(name) for name in bundle.namelist()}
        files['Application/Server.exe'] = executable.read_bytes()
        info = json.loads(files['Application/BUILD-INFO.json'])
        info['files']['Server.exe'] = sha(executable.read_bytes())
        files['Application/BUILD-INFO.json'] = json.dumps(info).encode()
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name, data in files.items():
                bundle.writestr(name, data)
        parent = subprocess.Popen([str(POWERSHELL), '-NoProfile', '-Command', 'Start-Sleep -Seconds 20'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        request.update(parent_pid=parent.pid, sha256=sha(archive.read_bytes()))
        plan.write_text(json.dumps(request), encoding='utf-8')
        helper = subprocess.Popen([str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(HELPER), '-Plan', str(plan), '-Headless'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            time.sleep(1)
            self.assertIsNone(helper.poll(), 'Installer did not wait for the parent')
            self.assertEqual((root / 'a.txt').read_bytes(), b'old-a')
            parent.terminate(); parent.wait(timeout=5)
            _, error = helper.communicate(timeout=20)
            self.assertEqual(helper.returncode, 0, error[-2000:])
            for _ in range(30):
                if (root / 'restarted.txt').exists():
                    break
                time.sleep(0.1)
            self.assertEqual((root / 'restarted.txt').read_text(), 'new program')
            for name, data in private.items():
                self.assertEqual((root / name).read_bytes(), data)
        finally:
            if parent.poll() is None:
                parent.terminate(); parent.wait(timeout=5)
            if helper.poll() is None:
                helper.terminate(); helper.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
