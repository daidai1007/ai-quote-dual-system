# Windows 安装包

build_installer.ps1 会依次生成“折弯双页”图标、重建带图标的 V3
客户端、复制运行依赖，并编译成一个中文 NSIS 安装包。旧卸载器与现有
output 报价文件不会进入安装包。

V3 核心已经保存在仓库的 `desktop_client/v3_core/`，两种客户端构建脚本
都先执行 `verify_v3_core.py` 校验，再从该目录收集核心，避免依赖现用
客户端中的隐式核心副本。`AIQuoteDualSystem_installer.spec` 也将其收集为
`v3_core` 数据。需要 CPython 3.12 x64 和 PyInstaller 6.x。

本次仅纳入核心，不代表空电脑已具备完整构建环境。脚本仍要求独立准备
`desktop_client/requirements.txt`、NSIS（安装包）、现有已验证客户端的
原生依赖目录 `_internal`、外部工具目录 `runtime`、项目许可证/第三方声明
及本机 `client_config.json`。这些运行配置及业务凭据不随核心上传。
数据库、客户模板和 OCR 模型也不由本目录核心替代。

默认输出位置：

G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem_Installer\AIQuoteDualSystem_Setup_v2026.08.21.4.exe

安装采用当前用户模式，默认目录为
%LOCALAPPDATA%\Programs\AIQuoteDualSystem，无需管理员权限。目录页允许
用户选择其他可写磁盘和文件夹。
