# 报价方案中心 V1 部署步骤

1. 先备份生产数据库，并在隔离测试库执行 `quote_scheme_center_v1.sql`。
2. 验证 `calc.next_quote_scheme_number()` 连续调用得到唯一的 `BJ-YYYYMMDD-六位流水号`。
3. 为 API 配置 `AI_QUOTE_PRINCIPALS_JSON`。该值是 JSON 数组，每项仅保存 API 密钥的 SHA256，不保存明文密钥：
   `[{"api_key_sha256":"...","user_id":"...","display_name":"...","department_id":"...","role":"USER|DEPARTMENT_MANAGER|ADMIN"}]`。
4. 先部署包含报价方案接口的新 API，再部署桌面客户端。身份映射缺失时方案接口会返回 503，不会创建匿名或伪造身份记录。
5. 用普通人员、部门负责人和管理员三个真实测试账号分别验证列表和详情权限；不得共用同一个密钥哈希。
6. 完成验证后再启用生产流量。若只部署客户端而未部署迁移/API，报价方案页面会显示服务尚未部署，原报价计算、打印和导出仍可使用。

复制方案会生成新的 `BJ-...` 编号并记录来源方案；创建修订版沿用原主方案编号，把当前已报价快照冻结到 `calc.quote_scheme_version`，然后进入 V2/V3 修订，不覆盖既有版本。

本迁移不修改报价公式、快速报价、附件匹配、折扣、运费、图纸识别或 Excel 模板规则。
