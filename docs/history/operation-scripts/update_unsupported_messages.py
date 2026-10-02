"""Update only the reviewed local diagnostic files, preserving a rollback copy."""
import hashlib
import json
import os
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SOURCE = BASE/'outputs/Slidex工作台.app/Contents/Resources'
TARGET = Path('/Applications/Slidex工作台.app/Contents/Resources')
BEFORE = BASE/'work/unsupported-message-before'
BACKUP = BASE/'work/installed-unsupported-backup'
FILES = ('browser_task.py','browser_bridge.py','web/app.js','web/index.html')

assert TARGET.resolve() == TARGET, 'Unexpected application path'
for name in FILES:
    target = TARGET/name
    assert target.is_file() and not target.is_symlink(), name
    assert target.read_bytes() == (BEFORE/name).read_bytes(), f'Installed file changed: {name}'
    backup = BACKUP/name
    backup.parent.mkdir(parents=True,exist_ok=True)
    if backup.exists():
        assert backup.read_bytes() == target.read_bytes(), f'Backup differs: {name}'
    else:
        shutil.copy2(target,backup)

changed = []
try:
    for name in FILES:
        temporary = (TARGET/name).with_name((TARGET/name).name+'.diagnostic-update')
        assert not temporary.exists(), str(temporary)
        shutil.copy2(SOURCE/name,temporary)
        os.replace(temporary,TARGET/name)
        changed.append(name)
    for name in FILES:
        assert hashlib.sha256((SOURCE/name).read_bytes()).digest() == hashlib.sha256((TARGET/name).read_bytes()).digest()
except Exception:
    for name in changed:
        shutil.copy2(BACKUP/name,TARGET/name)
    raise
print(json.dumps({'updated_files':list(FILES),'hashes_match':True,'browser_operations':0},ensure_ascii=False))
