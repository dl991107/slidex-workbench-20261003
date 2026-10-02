# Slidex 工作台归档

归档日期：2026-10-03（Asia/Shanghai）。这是本次工作台、源码和测试记录的快照。

## 内容

- `outputs/Slidex工作台.app/Contents/`：当前工作台源文件、网页界面、Mac 启动器与应用配置。运行时单独随完整应用 ZIP 提供。
- `vendor/slidex/`：实际使用的 Slidex 0.6.28 源码快照及上游测试、文档。
- `work/workbench-tests/`：工作台接口、参数、去重、并发、取消、超时与结果说明检查。
- `work/test_browser_ui_logic.cjs`：前端状态检查。
- `docs/history/`：历史本地/公开样例测试结果、说明、旧预览，以及诊断修复前的源文件。

## 当前状态

工作台可由使用者连接本机 Chrome 调试端口并选择标签页。内置适配器为 `geetest` 与 `aliyun-nocaptcha`。
本次已修正 Unsupported 的原因提示；尚未完成当前目标网页的适配，没有该网页验证成功的证据。
历史图片识别、人工构造样例、本机浏览器样例与接口测试，均不能作为真实网站验证通过的证据。
`Slidex工作台预览.png` 和 `check_workbench_ui.py` 属于早期图片工作台的历史记录，不是当前界面的验收入口。

## 从源码运行

使用 Python 3.12，在仓库根目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python outputs/Slidex工作台.app/Contents/Resources/server.py
```

服务启动后会打开本机工作台。连接与执行需要使用者点击；启动不自动连接网页。

## 工作台检查

```sh
.venv/bin/python -m pytest work/workbench-tests -q
node work/test_browser_ui_logic.cjs
node --check outputs/Slidex工作台.app/Contents/Resources/web/app.js
```

上述检查不连接真实网站或执行真实网站滑块。`vendor/slidex/tests` 是上游测试快照，未纳入本次工作台验收。
`docs/history/operation-scripts` 只保存当时的操作脚本，带有已经脱敏的旧机器路径/进程信息，不应直接运行。

## 完整应用与 Git 备份

完整 Mac 应用为 Apple Silicon（arm64）构建，含 Python 和依赖，随 `slidex-workbench-macos-arm64.zip` 发布。
源码 ZIP 与 Git bundle 单独提供；bundle 可用 `git clone <bundle 文件> slidex-workbench` 恢复。
归档未包含浏览器 Profile、Cookie、账号密码、会话 token、调试浏览器标识或服务运行日志。

## 第三方来源

Slidex 上游：https://github.com/dengyie/slidex ，上游声明 MIT。保留了源快照的项目元数据和文档。
样例与预测图来自 https://github.com/chenwei-zhao/captcha-recognizer ，来源及引用记录位于历史报告。
本工作台新增代码未额外声明对外许可证；预编译依赖的许可证保留在应用运行时包内。
