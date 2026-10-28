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
    def test_parameter_shortcuts_load_pinned_framework_and_configured_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, APP_ENV=str(ROOT / 'setenv.sh'), OSE_PYTHON=sys.executable,
                       FRAMEWORK_ROOT='/previous/framework', OSE_APP_ROOT='/previous/application')
            env.pop('OSE_PARAMETER_TOKEN', None)
            env.pop('OSE_PARAMETER_CLIENT', None)
            script = '''set -eu
shopt -s expand_aliases
source "$APP_ENV"
type params-list params-get params-get-all params-set params-watch params-sync >/dev/null
"$OSE_PYTHON" - <<'PYTHON'
import json, os
from pathlib import Path
root = Path(os.environ['OSE_APP_ROOT'])
configuration = next(root / name for name in ('build/plan.json', 'deployment.local.json', 'deployment.json')
                     if (root / name).is_file())
expected = json.loads(configuration.read_text()).get('parameter_clients', {}).get('operator', {}).get('token')
print(json.dumps({'application': str(root), 'framework': os.environ['FRAMEWORK_ROOT'],
                  'token_matches': os.environ.get('OSE_PARAMETER_TOKEN') == expected}))
PYTHON
'''
            result = subprocess.run(['bash', '--noprofile', '--norc', '-c', script],
                                    cwd=temporary, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'application': str(ROOT),
                'framework': str(ROOT / 'deps/sdl-ose'), 'token_matches': True})

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
