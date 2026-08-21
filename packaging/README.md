# Windows 安装包

build_installer.ps1 会依次生成“折弯双页”图标、重建带图标的 V3
客户端、复制运行依赖，并编译成一个中文 NSIS 安装包。旧卸载器与现有
output 报价文件不会进入安装包。

默认输出位置：

G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem_Installer\AIQuoteDualSystem_Setup_v2026.08.21.4.exe

安装采用当前用户模式，默认目录为
%LOCALAPPDATA%\Programs\AIQuoteDualSystem，无需管理员权限。目录页允许
用户选择其他可写磁盘和文件夹。
