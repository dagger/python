from pathlib import Path
from zipfile import ZipFile, ZipInfo

Path('/wheels').mkdir()
for name, version, requirements in [
    ('conflicting_tool', '0.2.0', ['packaging<25']),
    ('packaging', '25.0', []),
]:
    info = f'{name}-{version}.dist-info'
    files = {
        f'{info}/METADATA': f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n' +
            ''.join(f'Requires-Dist: {req}\n' for req in requirements),
        f'{info}/WHEEL': 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
        f'{info}/RECORD': '',
    }
    with ZipFile(f'/wheels/{name}-{version}-py3-none-any.whl', 'w') as wheel:
        for path, contents in files.items():
            wheel.writestr(ZipInfo(path), contents)
