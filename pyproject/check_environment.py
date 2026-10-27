from pathlib import Path
import re
import subprocess
import sys
import sysconfig
import tempfile

requirements = [req for req in sys.argv[1:] if re.match(
    r'^[A-Za-z0-9][A-Za-z0-9._-]*\s*(?:\[[^\]]+\]\s*)?(?:\(\s*)?[<>=!~]', req.strip())]
with tempfile.TemporaryDirectory(prefix='dagger_tools_', suffix='x-0.dist-info', dir=sysconfig.get_path('purelib')) as info:
    name = re.sub(r'[-_.]+', '-', Path(info).name[:-len('-0.dist-info')]).lower()
    Path(info, 'METADATA').write_text('Metadata-Version: 2.1\nName: '+name+'\nVersion: 0\n'+
        ''.join('Requires-Dist: '+req+'\n' for req in requirements))
    Path(info, 'WHEEL').write_text('Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
    Path(info, 'RECORD').touch()
    check = subprocess.run(['uv', '--color', 'never', 'pip', 'check', '--python', sys.executable],
        capture_output=True, text=True)
if check.returncode not in (0, 1):
    sys.exit(check.stdout + check.stderr)
problems = []
for line in (check.stdout + check.stderr).splitlines():
    if not line.startswith('The package '):
        continue
    requested = line.startswith('The package `'+name+'`')
    if requested or re.search(r', but `[^`]+` is installed$', line):
        problems.append(line.replace('The package `'+name+'` requires', 'The requested tools require'))
if problems:
    sys.exit('\n'.join(problems))
