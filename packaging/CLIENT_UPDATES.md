# 客户端在线更新（当前仅本地验证，未配置公网）

## 当前行为

- 原来的选型、报价、附件、成本和导出逻辑不改。沿用蓝白弹窗和绿色进度条。
- 启动后延迟在工作线程检查版本；不阻塞界面，不自动下载，不强制退出。
- 左侧“检查更新”可手动检查；发现新版后顶部显示提示，查看更新说明后人工点击下载。
- 下载与签名/哈希校验成功后，人工点击“保存进度并重启更新”。
- 正在报价、识别、保存或导出登记时不能更新。保存失败或原关闭保护拒绝退出时不安装。
- 重启前将当前选型填写、报价、明细、附件和图纸保存为 `.aiquote` 本机恢复文件；新版本/恢复旧版时携带这个文件启动。
- 独立更新进程从旧 EXE 与旧 `_internal` 的缓存副本运行，等待原进程自然退出，不强杀使用人员的进程。
- 先备份文件，再逐个原子替换，启动新版本并等待真实主窗口健康回执；失败则恢复旧文件并重新打开旧版。
- 更新结果在重启后的主界面提示。备份和事务日志保留，不自动删除。

没有 `update_config.json` 或 `enabled` 为 false 时，启动不访问更新服务器。“检查更新”显示尚未配置。
本次不上传任何文件、不修改数据库/API，也不覆盖现用 EXE。

## 用户文件保护边界

更新 ZIP 只允许主 EXE、`_internal/`、`runtime/` 与指定许可证/图标。绝不覆盖：

- `client_config.json`、`update_config.json`；
- 用户的订单、图纸、报价导出、任意自定义本地文件；
- `%LOCALAPPDATA%` 内原有业务缓存和配置。

不接受符号链接/目录联接、越界路径、Windows 保留名、大小写重复路径、包含用户配置或私钥的更新包。
PEM 文件仅允许固定路径 `_internal/certifi/cacert.pem` 的公开 CA 证书包，构建和解包均验证 X.509 内容；私钥、其他 PEM 路径或伪装成证书的密钥仍会被拒绝。
清单采用 Ed25519 签名，公钥来自本机配置，不信任服务器下发的新公钥；下载包以 SHA-256 和准确字节数校验。
HTTP 默认仅允许本机环回测试；局域网 HTTP 必须额外配置精确的 `lan_http_origin`，只允许该 IP 和端口。
只支持标准私有 IPv4（10/8、172.16/12、192.168/16），不接受域名、CIDR、通配符、特殊地址或其他 IP/端口。
下载地址和清单必须同源，重定向同样受限；启用内网 HTTP 固定地址后，也不能跳转到其他 HTTPS 或本机地址。
HTTPS 的原有证书校验保留。不传报价 API 的认证头，不使用系统代理转发更新请求。
默认不启用公网。开发时可用 `AI_QUOTE_UPDATE_CONFIG` 指向测试配置，不需要改现用配置。

## 局域网 HTTP 配置（无需 HTTPS 证书）

先将包含更新功能及本次内网 HTTP 支持的客户端分发到使用人员电脑。旧 EXE 不会因修改配置就自动获得新功能。
服务器使用固定内网 IP；以下 `192.168.1.100:8897` 仅为示例，并未配置为实际地址。

在客户端 EXE 同目录的 `update_config.json` 中填写：

```json
{
  "enabled": true,
  "channel": "local",
  "manifest_url": "http://192.168.1.100:8897/stable/manifest.json",
  "lan_http_origin": "http://192.168.1.100:8897",
  "public_key": "开发人员生成并通过可信方式分发的Base64签名公钥"
}
```

- `lan_http_origin` 只填协议、IP、端口，不能带清单路径、查询参数或账号密码；不填写时不允许访问其他电脑的 HTTP 更新服务。
- 清单与 ZIP 可放在这个服务器的不同路径，但 IP 和端口必须一致；清单中的 ZIP 地址必须由签名构建工具正确生成。
- 默认配置 `enabled: false`、`lan_http_origin: ""`，不会主动连接任何公司更新服务器。
- HTTP 传输不加密；包签名及 SHA-256 校验仍强制执行。下载目录不得放签名私钥、用户配置、订单或图纸。
- 仅允许公司内网访问下载端口，不要做公网端口映射；本次源码修改不会自动创建防火墙规则或启动服务。

例如，为版本 `2026.10.20.06` 构建独立版本目录：

```powershell
python packaging/make_client_update.py build --source <新客户端目录> --output D:/AIQuoteUpdates/2026.10.20.06 --private-key <私有目录>/update-signing.key --version 2026.10.20.06 --base-url http://192.168.1.100:8897/2026.10.20.06 --lan-http-origin http://192.168.1.100:8897 --notes <更新说明UTF8文件>
```

先上传完整版本目录，确认 ZIP 可下载且校验正确，最后再将新清单发布为 `stable/manifest.json`。
临时内网验证可在更新服务器上运行（替换为该电脑实际 IP，保持此窗口运行）：

```powershell
python -m http.server 8897 --bind 192.168.1.100 --directory D:/AIQuoteUpdates
```

这个目录只能存放用于下载的更新包和签名清单，不能将整个工程或私钥目录作为下载根目录。长期运行应由管理员配置常驻服务和内网访问控制。

## 一键本地模拟（建议先执行）

在项目目录用客户端 Python 执行：

```powershell
& 'G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe' packaging/simulate_client_update.py
```

模拟器在 `outputs/local-update-simulation-随机编号/` 新建独立目录，编译微型测试 EXE，
启动只监听 `127.0.0.1` 的临时文件服务，测试真实签名、下载、安装、进程启动与失败恢复。
正常更新和失败恢复各执行一次，检查配置、图纸、订单和导出文件的字节不变。
测试只关闭自己启动的测试进程。测试结束后关闭本机 HTTP 服务，保留结果和备份。
**微型测试 EXE 不是业务客户端，不可发给使用人员。**

## 自动化测试

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:AI_QUOTE_V3_CORE_ROOT='G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\_internal\v3_core'
& 'G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe' tests/verify_client_updates.py
& 'G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe' tests/verify_lan_client_updates.py
& 'G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe' tests/verify_client_update_ui.py
```

界面测试截图位于 `outputs/client-update-qa/`。源码模式可以检查和下载，但禁止替换现用客户端；
真正的业务 EXE 替换须在隔离打包副本验证后才可发布。基础的“启动成功”不代表报价/API兼容性测试通过。

打包后还可运行以下测试：它调用打包 EXE 的真实独立更新入口，目标仍是可丢弃的微型模拟客户端：

```powershell
python tests/verify_review_package.py <隔离打包客户端目录>
python tests/verify_client_update_bundle.py <隔离打包客户端目录>
python tests/verify_client_update_bundle.py <隔离打包客户端目录> --lan-http
```

内网专项测试使用明确的私有 IP 作为请求地址，但将测试 TCP 连接只路由到本机环回服务；不向公司网络开放测试下载服务。

只有构建物包含最新源码、签名验证依赖以及正常更新/回滚的进程测试均通过后，才继续业务副本验收。

## 日后准备实际内测包（当前不执行公网发布）

1. 先统一修改客户端源码版本号，再构建并测试独立的完整客户端目录。只改打包文件名不算新版本。
2. 在下载目录之外生成签名私钥并妥善保管，私钥绝不能发给使用人员：

```powershell
python packaging/make_client_update.py keygen --private-key <私有目录>/update-signing.key
```

3. 使用构建产物创建程序专用更新包：

```powershell
python packaging/make_client_update.py build --source <新客户端目录> --output <新版本下载目录> --private-key <私有目录>/update-signing.key --version 2026.10.20.05 --base-url http://127.0.0.1:8897 --notes <更新说明UTF8文件>
```

4. 用只暴露该下载目录的本地 HTTP 服务测试，在隔离旧客户端旁边配置：

```json
{
  "enabled": true,
  "channel": "local",
  "manifest_url": "http://127.0.0.1:8897/manifest.json",
  "public_key": "keygen输出的Base64公钥"
}
```

`manifest.json` 是签名版本说明；ZIP 只含程序文件。构建器不会把现用客户端配置打进更新包。
初次安装包仍由现有安装流程分发；以后内置更新可代替重复发整套安装包。

## 恢复与限制

事务位于 `%LOCALAPPDATA%/AIQuoteDualSystem/updates/<安装路径摘要>/<事务编号>/`，包含
`job.json`、`backup/`、隔离 `runner/` 与更新前进度文件。不要删除失败现场。
正常异常自动恢复；若整个更新进程被中断，可关闭所有客户端后，从该事务的旧运行时副本执行：

```powershell
& '<事务目录>/runner/AIQuoteDualSystem_layout_v0.exe' --client-updater '<事务目录>/job.json'
```

已记入日志的中断事务会恢复旧版，而不会继续盲目覆盖。恢复也失败时明确提示人工处理，不伪报“已恢复”。
若文件被其他客户端占用，不强杀它们；本次更新停止。安装在不可写目录时需先移到可写的用户目录。
当前是单通道、程序文件增量覆盖模型，不删除未知/旧文件、不执行数据库迁移、不支持任意更新脚本。
