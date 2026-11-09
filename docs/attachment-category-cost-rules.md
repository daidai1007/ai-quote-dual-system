# 控制柜与控制箱附件的跨产品成本规则

报价附件以选中的目录分类确定结构公式。控制柜附件使用该目录项绑定的控制柜规则，控制箱附件使用其绑定的控制箱规则。JM 的两类防雨顶分别沿用 JP/JS 和 JA/JE 的对应公式。

API 先保留明确的产品专用和通用规则。如果这两类附件没有当前产品可用的规则，则在该目录项已经绑定的普通规则中选择，继续校验材质与同级冲突。JP/JS 超宽产品原有的专用防雨顶规则继续适用。计算使用实际尺寸、材质和系数，并保留原报价产品编号。

## 人工更新范围

API 文件为 api/attachment_cost.mjs。现有数据库快照触发器还会调用 calc.resolve_attachment_cost_rule(bigint,text,text) 校验成本规则，因此正式保存需要配套更新这个函数。单独部署 API 可预览新成本，旧函数会拒绝跨产品规则的保存。

database/migrations/attachment_category_cost_rules.sql 是待人工执行的兼容脚本。它替换规则选择函数，保留目录、公式原文、绑定、历史快照以及既有快照保护。程序不会自动执行此脚本。

人工部署应在同一个维护窗口协调 API 和函数更新，暂停相关计算保存操作，先保存目标环境中该函数的定义，再复核并执行脚本、部署 API，随后验证 JM 两类防雨顶的预览、保存及数量修改。备份定义可通过以下只读语句取得。

    SELECT pg_get_functiondef(
      'calc.resolve_attachment_cost_rule(bigint,text,text)'::regprocedure
    );

已有报价行保留冻结结果，重新计算会创建新快照。若回退，需要配套回退 API 并恢复先前保存的函数定义。

## 回归

离线测试覆盖原公式的明确金额、多个产品与目录类目的交叉选择、材质限制、超宽规则，以及原仅面价行重新计算后保存为新快照。

    node --test tests/attachment_cost_v2.test.mjs tests/size_matched_attachment_prices.test.mjs tests/attachment_snapshot_refresh.test.mjs tests/standalone_attachment.test.mjs tests/attachment_catalog_precision.test.mjs

数据库集成测试仅在新建、回环连接且自动清理的临时 PostgreSQL 实例中运行。测试先证明旧函数拒绝跨产品快照，再在临时实例中加载兼容脚本，验证两类防雨顶的真实保存、数量修改及原快照保留。

    $env:ATTACHMENT_REFRESH_DB_TEST='1'
    node --test tests/attachment_snapshot_refresh_database.test.mjs
