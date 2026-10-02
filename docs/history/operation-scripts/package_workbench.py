"""Build a local Mac app using the already installed, isolated dependencies."""
import plistlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT/'outputs/Slidex工作台.app'
CONTENTS = APP/'Contents'
RESOURCE = CONTENTS/'Resources'
SOURCE = Path('<USER_HOME>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python')
RUNTIME = RESOURCE/'runtime'

if not (RUNTIME/'.complete').exists():
    shutil.copytree(SOURCE,RUNTIME,dirs_exist_ok=True,ignore_dangling_symlinks=True,
                    ignore=shutil.ignore_patterns('site-packages','__pycache__'))
    shutil.copytree(ROOT/'work/venv/lib/python3.12/site-packages',
                    RUNTIME/'lib/python3.12/site-packages',dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    (RUNTIME/'.complete').write_text('Python 3.12.14 / Slidex 0.6.28\n')

launcher = CONTENTS/'MacOS/launch'
launcher.write_text('''#!/bin/zsh
set -eu
resource_dir="$(cd -- "$(dirname -- "$0")/../Resources" && pwd)"
exec "$resource_dir/runtime/bin/python3.12" -E -s -B "$resource_dir/server.py" "$@"
''')
launcher.chmod(0o755)
with (CONTENTS/'Info.plist').open('wb') as file:
    plistlib.dump({'CFBundleName':'Slidex工作台','CFBundleDisplayName':'Slidex 工作台',
        'CFBundleIdentifier':'local.slidex.workbench','CFBundlePackageType':'APPL',
        'CFBundleExecutable':'launch','CFBundleShortVersionString':'1.1.0',
        'CFBundleVersion':'2','LSUIElement':True,'NSHighResolutionCapable':True},file)
print(APP)
