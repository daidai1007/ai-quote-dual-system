# 已验证的 V3 客户端核心

本目录保存当前客户端实际使用的 CPython 3.12 核心，已纳入 Git 版本管理。
`manifest.json` 记录每个二进制文件的大小和 SHA-256。此次入库文件与开发电脑
现用核心及已验证的 2026.10.23.01 客户端核心逐字节一致。

- `main.raw`：V3 主程序代码对象。
- 其他七个 `.raw`：图纸识别、复核、装配、工作台及基础 API 支持模块。
- `original.pyz`：原客户端的 Python 模块依赖归档，共 1451 个模块。

这些文件由 `desktop_client/v3_launcher.py` 加载，再叠加仓库内维护的界面、
计价、合同和其他功能模块。它们是已编译的核心，不是可直接编辑的 Python
文本源码；不要用仓库中的旧版 `desktop_client/main.py` 重新生成或覆盖。

## 校验与加载

使用 **Windows x64、CPython 3.12**。首先在仓库根目录校验：

```powershell
python packaging/verify_v3_core.py
```

源码运行默认读取本目录，无需设置 `AI_QUOTE_V3_CORE_ROOT`。只有需要明确验证
另一份核心时才设置该环境变量；如之前设置过，应清除后再验证仓库副本。
启动还需要安装 `desktop_client/requirements.txt`、PyInstaller 6.x，并配置
实际使用的 API。`original.pyz` 不包含所有原生 DLL、OCR 模型和外部工具。

## 构建

安装包及本地验收构建脚本均使用本目录核心，并把核心校验清单一同带入构建物。
PyInstaller spec 也会将它作为 `v3_core` 数据收集。
现有构建脚本仍从经过验证的客户端目录取其他原生运行库及外部工具；详情见
`packaging/README.md`。本次核心入库未执行构建、覆盖客户端或发布服务。

本目录不包含客户端连接配置、密钥、数据库备份、客户模板、图纸或业务数据。
保留项目根目录的许可证。依赖归档内第三方组件仍遵循各自原有许可。
