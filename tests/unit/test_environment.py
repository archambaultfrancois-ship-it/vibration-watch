"""Application shell inspection uses the pinned framework and user limits."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('bash'), 'requires Bash')
class EnvironmentTests(unittest.TestCase):
    def test_record_inspect_uses_submodule_without_adding_a_default_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            python = Path(temporary) / 'selected python'
            python.write_text('#!' + sys.executable + '\nimport json, os, sys\n'
                              'print(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()}))\n')
            python.chmod(0o755)
            env = dict(os.environ, APP_ENV=str(ROOT / 'setenv.sh'), OSE_PYTHON=str(python),
                       FRAMEWORK_ROOT='/previous/framework', OSE_APP_ROOT='/previous/application')
            command = 'set -eu\nshopt -s expand_aliases\nsource "$APP_ENV"\nrecord-inspect "$@"\n'
            for options in ([], ['--limit', '3']):
                with self.subTest(options=options):
                    result = subprocess.run(['bash', '--noprofile', '--norc', '-c', command,
                                             'test', 'capture with spaces.pcapng', *options],
                                            cwd=temporary, env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    call = json.loads(result.stdout)
                    self.assertEqual(call['cwd'], str(ROOT))
                    self.assertEqual(call['args'], [str(ROOT / 'deps/sdl-ose/sdl/tools/recording/sdl-recording'),
                        'inspect', '--format', 'text', 'capture with spaces.pcapng', *options])
