"""Install the explicitly requested new app without overwriting an existing one."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'outputs/Slidex工作台.app'
destination=Path('/Applications/Slidex工作台.app')
if destination.exists() or destination.is_symlink():
    raise SystemExit('Exact installation target already exists; no files changed.')
shutil.copytree(source,destination,ignore=shutil.ignore_patterns('__pycache__'))
for relative in ['Contents/Info.plist','Contents/MacOS/launch',
                 *['Contents/Resources/'+name for name in ['server.py','browser_bridge.py','browser_task.py','web/index.html','web/app.js','web/style.css']]]:
    assert hashlib.sha256((source/relative).read_bytes()).digest()==hashlib.sha256((destination/relative).read_bytes()).digest()
print(json.dumps({'installed':str(destination),'source_files_match':True},ensure_ascii=False))
