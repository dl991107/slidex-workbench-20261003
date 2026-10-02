import json
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT/'outputs/Slidex工作台.app'
PORT = ROOT/'work/workbench-ui-port.json'
BROWSER = '<USER_HOME>/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell'
REPORT = {'checks':[]}

process = subprocess.Popen([str(APP/'Contents/MacOS/launch'),'--no-open','--port-file',str(PORT)],
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
try:
    first_line = process.stdout.readline()
    origin = json.loads(first_line)['url']
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=BROWSER,headless=True)
        page = browser.new_page(viewport={'width':1360,'height':950},device_scale_factor=1)
        errors, remote = [], []
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:remote.append(request.url) if request.url.startswith(('http:','https:')) and not request.url.startswith(origin+'/') else None)
        page.goto(origin)
        expect(page.locator('#statusText')).to_contain_text('在线')
        expect(page.locator('#runButton')).to_be_disabled()
        expect(page.locator('#resultContent')).to_be_hidden()
        REPORT['checks'].append('packaged launcher and empty state')

        page.locator('#mainImage').set_input_files(str(ROOT/'work/public-puzzle-samples/example4.png'))
        expect(page.locator('#sceneCanvas')).to_be_visible()
        expect(page.locator('#canvasEmpty')).to_be_hidden()
        with page.expect_response(lambda response:response.url.endswith('/api/analyze')) as response:
            page.locator('#runButton').click()
            expect(page.locator('#resetButton')).to_be_disabled()
        data = response.value.json()
        assert response.value.status == 200 and data['result']['success']
        assert abs(data['result']['gap_x']-238) <= 3
        expect(page.locator('#resultState')).to_have_text('候选已生成')
        expect(page.locator('#resultEmpty')).to_be_hidden()
        expect(page.locator('#resultContent')).to_be_visible()
        expect(page.locator('#gapValue')).to_have_text(f"{data['result']['gap_x']} px")
        page.screenshot(path=str(ROOT/'outputs/Slidex工作台预览.png'),full_page=True)
        with page.expect_download() as download:
            page.locator('#exportButton').click()
        exported = json.loads(Path(download.value.path()).read_text())
        assert exported['result'] == data['result']
        REPORT['public_sample_result'] = data['result']
        REPORT['checks'].append('real Slidex public image + visible candidate + matching JSON export')

        page.locator('#mainImage').set_input_files(str(ROOT/'outputs/offline-puzzle-test/clean.png'))
        expect(page.locator('#resultContent')).to_be_hidden()
        expect(page.locator('#exportButton')).to_be_disabled()
        page.locator('#pieceImage').set_input_files(str(ROOT/'outputs/offline-puzzle-test/clean-piece.png'))
        with page.expect_response(lambda response:response.url.endswith('/api/analyze')) as response:
            page.locator('#runButton').click()
        assert response.value.status == 200 and response.value.json()['result']['success']
        REPORT['checks'].append('optional separate piece + stale result cleared')

        page.locator('#mainImage').set_input_files({'name':'broken.png','mimeType':'image/png','buffer':b'broken image'})
        with page.expect_response(lambda response:response.url.endswith('/api/analyze')) as response:
            page.locator('#runButton').click()
        assert response.value.status == 422
        expect(page.locator('#resultContent')).to_be_hidden()
        expect(page.locator('#exportButton')).to_be_disabled()
        expect(page.locator('#inputError')).to_be_visible()
        page.locator('#mainImage').set_input_files({'name':'bad.txt','mimeType':'text/plain','buffer':b'text'})
        expect(page.locator('#runButton')).to_be_disabled()
        expect(page.locator('#mainName')).to_have_text('尚未选择')
        page.locator('#resetButton').click()
        expect(page.locator('#pieceName')).to_have_text('未添加拼块')
        expect(page.locator('#inputError')).to_be_hidden()
        REPORT['checks'].append('invalid file and damaged image rejected without stale results; reset')

        for width in (320,375,1360):
            page.set_viewport_size({'width':width,'height':950})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'overflow at {width}'
        REPORT['checks'].append('no horizontal overflow at 320 / 375 / 1360 px')
        page.locator('#shutdownButton').click()
        expect(page.locator('#statusText')).to_have_text('服务已关闭')
        expect(page.locator('#runButton')).to_be_disabled()
        assert process.wait(timeout=5) == 0
        assert not errors, errors
        assert not remote, remote
        REPORT['checks'].append('clean shutdown; no JS errors or external requests')
        browser.close()
    (ROOT/'outputs/Slidex工作台验证.json').write_text(json.dumps(REPORT,ensure_ascii=False,indent=2))
    print(json.dumps(REPORT,ensure_ascii=False))
finally:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
