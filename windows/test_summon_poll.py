"""Exercise shipped start commands without starting real account or game services."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('server_poll_test',HERE/'package-src/server.py')
server=importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class Process:
    def poll(self):return None
    def terminate(self):pass
    def wait(self,timeout):return 0


class Opener:
    def open(self,url,timeout):
        return io.BytesIO(b'{"ok":true}' if url.endswith('/status') else b'base64-ss-info')


class SummonPollTests(unittest.TestCase):
    def commands(self,mode):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/mode).mkdir()
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(server,'ROOT',root))
                stack.enter_context(patch.object(server,'profile',return_value=('127.0.0.2',{})))
                stack.enter_context(patch.object(server,'require_free'))
                stack.enter_context(patch.object(server,'print_client_settings'))
                stack.enter_context(patch.object(server,'environment',return_value={}))
                stack.enter_context(patch.object(server.subprocess,'CREATE_NO_WINDOW',0,create=True))
                processes=stack.enter_context(patch.object(server.subprocess,'Popen',side_effect=lambda *a,**k:Process()))
                stack.enter_context(patch.object(server.urllib.request,'build_opener',return_value=Opener()))
                stack.enter_context(patch.object(server.time,'sleep',side_effect=KeyboardInterrupt))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                server._start(mode)
                return [call.args[0] for call in processes.call_args_list]

    def test_only_seamless_game_service_has_two_second_interval(self):
        commands=self.commands('bbsc')
        self.assertEqual(len(commands),2)
        self.assertTrue(commands[0][0].endswith('shadnet.exe'))
        self.assertNotIn('--summon-interval',commands[0])
        game=commands[1]
        self.assertTrue(any(value.endswith('bbsc_gameserver.py') for value in game))
        self.assertEqual(game.count('--summon-interval'),1)
        self.assertEqual(game[game.index('--summon-interval')+1],'2')
        self.assertIn('--no-bbhost',game)

    def test_normal_coop_keeps_shadnet_only(self):
        commands=self.commands('normal')
        self.assertEqual(len(commands),1)
        self.assertTrue(commands[0][0].endswith('shadnet.exe'))
        self.assertNotIn('--summon-interval',commands[0])


if __name__=='__main__':unittest.main()
