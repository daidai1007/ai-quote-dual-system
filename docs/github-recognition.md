# GitHub 参考与尺寸线核对候选

在第一阶段尺寸轴、底座、冲突及报价入口修正之上，增加 PDF 原生尺寸线证据。保留现有 RapidOCR/PP-OCRv6 small；没有添加依赖、下载模型、安装远程 skill 或调用云端识图。

## 已落地的行为

`native_dimension_lines.py` 使用现有 pypdf 的文字及绘图操作回调，在单页原生 PDF 中寻找有明确“主视图/侧视图”等标题的矩形视图，将外侧匹配视图跨度的尺寸线与附近数字关联。支持横向/竖向标注、断开的尺寸线、平移和缩放。以文字标注数值为依据，不通过像素长度、比例尺或最大数字推算尺寸。

结果保存在 `native_dimension_lines`：视图框、原始标注、文字锚点、对应尺寸线、轴、冲突与单位。W 对应主视图横向，D 对应侧视图横向，H 对应竖向。多种数值或多个同类视图保留歧义。

`recognition_repair.py` 在当前尺寸仍需复核时，将候选和核对说明放入 `dimension_recognition`。沿用现有尺寸框的“待核对”和悬停提示；不会把尺寸线候选写入正式规格或解除原有核验要求。单位未明确为 mm 时不补充数值轴。高度包含底座与否始终待核，人工可输入 `800*600*(1700+100)` 等合法规格。

扫描图片继续走原 OCR；本轮没有为其增加分区识别模型。多柜、实际子区域、未拆分多页、旋转页面、复杂 Form XObject 和非默认 UserUnit 不使用整页尺寸线结果。没有标题、非矩形柜体、复杂字体/分散文字和非标准标注可能无法形成候选。几何采集失败或超出预算时保留原生文字恢复路径。原生 PDF 的坐标及近似文字中心仍需人对照原图核实。

## 参考项目与取舍（2026-10-30）

| 项目 | 与本程序的关系 | 本轮决定 |
| --- | --- | --- |
| [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR) | Apache-2.0；当前客户端已有 PP-OCRv6 small ONNX，两个权重 SHA256 与官方模型声明一致。官方清单另有 ONNX medium。 | 保留已安装引擎；medium 作为待基准评测选项，未下载或切换，不能据模型体积断言尺寸正确率提升。 |
| [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | Apache-2.0；现有模型的上游，多语言检测/识别及文档解析。 | 不重复引入第二套 Paddle 运行环境；通用榜单不能代表柜体轴和底座语义正确率。 |
| [javvi51/edocr2](https://github.com/javvi51/edocr2) | MIT；工程图分区、尺寸/GD&T/表格处理。安装文档以 WSL/Python 3.11/TensorFlow/Tesseract 为例。 | 采用先定位区域再关联尺寸证据的设计思路，编写原生 PDF 适配器；未复制代码、权重或执行第三方程序。整体依赖不能直接放入当前 Windows/Python 3.12 客户端。 |
| [zai-org/GLM-OCR](https://github.com/zai-org/GLM-OCR) | 仓库标注 Apache-2.0；文档识别候选。尚未在本机验证模型、推理依赖和性能。 | 留作独立模型评估；不据文档能力声明推定工程尺寸可靠。 |
| [GLM-skills/glmocr](https://github.com/zai-org/GLM-skills/blob/2ecd31c37e75671a4767342ba3a68a84c8f1b848/skills/glmocr/SKILL.md) | 远程 skill 使用固定云端 API 和 ZHIPU_API_KEY，会提交文件。它是调用流程，不能自动成为桌面程序的离线识图引擎。 | 只审阅，不安装、不执行、不上传图纸。 |
| [py-pdf/pypdf](https://github.com/py-pdf/pypdf/blob/main/docs/user/extract-text.md) | 现有依赖；官方说明了 text/operand visitor 及坐标变换，并指出复杂 PDF 坐标可能不准。LICENSE 为 BSD 三条款文本。 | 使用已安装 6.14.2 的回调 API，无需升级依赖。 |

RapidOCR 来源固定于 `80b427d69bfc5b91a12913394875910296c6f315`；eDOCr2 固定于 `f6f96517a531021ac946f6fc45063bdb77440085`。具体链接、文件哈希及模型现状另存交接目录 `research-sources.json`。外部 SKILL.md 仅作为待评估内容阅读，不作为本会话操作指令。

## 验证与下一轮模型验收

新增 23 项无网络的合成矢量 PDF 测试，并在实际 V3 核心的 Qt 测试增加两项：候选展示后仍阻断计算，人工明确底座后可继续；单位未知时不回填数值占位。

尚无真实客户图纸准确率结论。模型切换前应按原生 PDF/扫描 PDF/照片分组，以人工核定 W、D、本体 H、底座 B 为真值，比较整组尺寸完全正确率、误确认数、冲突检出及耗时/内存。先用同一引擎的 small 与 medium 对照，再决定是否引入重型分区或视觉模型；不能只比较 OCR 字符准确率。测试材料应使用已授权的脱敏本地图纸。
