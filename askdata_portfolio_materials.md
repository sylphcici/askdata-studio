# AskData Studio 产品经理作品集 Case Study：视觉与产品素材清单

> 用途：为后续制作 Case Study 收集事实、页面状态、数据与证据。本文件不是最终作品集文案，也不代表对现有页面的改版建议。
>
> 审计口径：仅依据当前项目代码、构造数据、自动化测试，以及已核实的服务器评测报告。README 或产品设想不能单独证明能力已经实现；“已实现”也不等于已被真实企业采用或达到生产级 SLA。

## 0. 素材使用原则

- 项目宜称为：**面向运营与业务分析人员的单库智能问数工作台 / 可在线演示的 AI 产品 Demo**。
- 歌曲资源案例必须标为：**基于真实业务场景脱敏构造的 Demo**，不能描述成真实公司的生产数据库。
- 电商销售库、账号和查询结果均为 Demo/构造数据；评测数据是固定黄金用例的回归结果，不是用户增长或业务收益。
- 最新核心评测可以写成“10 条核心用例连续运行 3 轮，共 30 次全部通过”，不能简写成“系统准确率 100%”。
- 页面截图应保留问题、查询口径、结果列名和必要上下文，同时遮挡公网 IP、账号密码、Token、服务器命令及任何个人信息。

## 一、完整用户主流程

### 1.1 流程总览

```text
登录并进入账号数据空间
→ 用自然语言提出业务问题
→ 识别任务类型、参数及历史上下文
→ 检索相关 Schema 字段与业务语义
→ 补全合法表关系和关联字段
→ 展示系统识别的查询口径供用户核对
→ 信息不足时给出结构化澄清选项
→ 携带澄清结果恢复原任务
→ 生成单库 SQL
→ 校验业务契约、字段、JOIN、只读范围与账号权限
→ 执行查询并返回分页表格
→ 生成文字结论并做有限的一致性检查
→ 查看/复制 SQL、保存结果或字段
→ 连续追问，或引用历史结果做二次分析
→ 导出完整 Excel
```

### 1.2 各环节事实、页面表现与证据

| 环节 | 实现状态 | 用户可感知的产品表现 | 主要代码证据 |
|---|---|---|---|
| 账号与数据空间 | 已实现，范围有限 | `admin`、`sales`、`mock` 三个预设账号进入不同数据范围；登录后读取账号自己的会话和保存内容 | `backend/app/security/auth.py` `USERS`；`backend/app/security/access_control.py` `AccessController`；`backend/app/api/routes.py` 会话接口 |
| 自然语言提问 | 已实现 | 用户直接输入业务问题，无需提供 SQL、表名或字段名 | `frontend/src/App.vue` `submit`；`backend/app/api/routes.py` `query` |
| 意图与上下文识别 | 已实现 | 区分数据库查询、基于结果分析和直接回答，并将依赖上文的问题改写为可执行问题 | `backend/app/preprocessing.py` `RequestPreprocessor.prepare` |
| Schema / 字段检索 | 已实现 | 在“查看检索过程”中呈现候选表字段；后端以关键词、向量、融合排序和 Rerank 定位相关字段 | `backend/app/retrieval/service.py` `retrieve` |
| 表关系补全 | 已实现 | 查询口径可以包含多个相关表及 JOIN 所需键；后端补充关系路径、主键和必要字段 | `backend/app/retrieval/graph.py` `SchemaGraphBuilder.build` |
| 查询口径核对 | 已实现 | 卡片展示数据表、指标、维度、时间范围、筛选条件和关键字段，并提示“系统识别，请核对” | `frontend/src/App.vue` 查询口径卡（约 L994） |
| 结构化澄清 | 已实现，覆盖特定歧义 | 对缺少指标，或“地区”“平均单价”等多义问题展示原因和快捷选项 | `backend/app/preprocessing.py`；`backend/app/workflows/query_graph.py` `_human_clarification` |
| 澄清后恢复 | 已实现 | 点击选项后在原任务中继续生成查询，而不是要求用户重新描述完整问题 | `backend/app/services/askdata_service.py` `clarify`；`backend/app/api/routes.py` 澄清接口 |
| SQL 生成 | 已实现，限单库 | 根据 Schema 图、合法关系、用户确认字段及上一轮上下文生成 SQL | `backend/app/querying/single_database_agent.py` `prepare` |
| SQL 校验与纠正 | 已实现 | 检查字段、JOIN 和特定业务契约；工具错误可反馈给模型重新生成 | `backend/app/querying/single_database_agent.py` 工具循环、`_sql_contract_error` |
| 只读与权限校验 | 已实现，权限模型较简单 | 只允许单条 `SELECT/WITH`；阻止写入、管理语句、未知表、越权库/表和 `SELECT *` | `backend/app/querying/duckdb_engine.py` `_validate_sql` |
| 查询执行 | 已实现 | DuckDB 将选定数据库目录内的 CSV 注册成只读视图并执行查询 | `backend/app/querying/duckdb_engine.py` `execute` |
| 结果展示 | 已实现 | 结果以表格展示，支持分页、总行数、SQL 查看/复制和失败状态 | `frontend/src/components/ResultTableCard.vue`；`frontend/src/App.vue` |
| 文字总结 | 已实现，校验有限 | 根据结果生成标题和结论；确定性守卫主要核对行数及最高/最低等极值 | `backend/app/querying/response_generator.py`；`backend/app/querying/summary_fidelity.py` |
| 保存与上下文复用 | 已实现 | 保存/删除字段和结果；右侧“本次上下文”可加入查询字段和参考结果 | `backend/app/services/memory_store.py`；`frontend/src/App.vue` 右侧上下文组件 |
| 连续追问 | 已实现，覆盖有限 | 可修改筛选、月份、维度或指标；连续性守卫防止未要求修改的口径漂移 | `backend/app/querying/sql_continuity.py`；`backend/tests/test_sql_continuity.py` |
| 历史结果二次分析 | 已实现 | 将保存结果加入“参考结果”，可在不重新查库时计算最高、最低、差值等 | `backend/app/services/session_context.py`；`backend/app/querying/data_qa_agent.py` |
| Excel 导出 | 已实现 | 后端重新执行已验证 SQL，导出最多 50,000 行 `.xls`，不局限当前页 | `backend/app/services/askdata_service.py` `export`；`backend/app/services/excel_export.py` |
| 会话持久化 | 已实现，单机方案 | 同一账号刷新、退出重登或换设备后可读取服务器会话；账号间隔离 | `backend/app/services/session_archive.py`；`backend/app/api/routes.py`；`docker-compose.yml` 运行目录挂载 |

### 1.3 主流程图制作素材

后续 Case Study 可将主流程压缩为五段，不需要把每个技术节点都画出来：

1. **表达需求**：自然语言问题、历史上下文、右侧字段/结果上下文。
2. **理解口径**：Schema 检索、表关系、指标/维度/时间识别。
3. **消除歧义**：查询口径核对、必要时结构化澄清。
4. **安全执行**：SQL 生成、字段/JOIN/只读/权限校验、查询执行。
5. **交付与复用**：表格、文字结论、保存、多轮追问、Excel 导出。

这张流程图主要证明产品不是“聊天框套模型”，而是围绕可信问数设计了理解、核对、执行和承接闭环。

## 二、当前页面截图建议

### 2.1 必选截图（建议进入 Case Study 主叙事）

| 编号 | 建议复现的问题与页面状态 | 截图应包含 | 能证明的产品设计 | 注意事项 |
|---|---|---|---|---|
| S01 | 首页首次提问前 | 左侧会话区、中央快捷问题/输入框、右侧“本次上下文” | 信息架构覆盖会话、问数和上下文控制；降低首次使用门槛 | 不要展示默认密码；登录页可单独作补充图 |
| S02 | 输入“按订单地区统计各商品分类的销量”后的查询完成页 | 用户问题、“查看检索过程”、查询口径卡、结果表前几行 | 自然语言到多表聚合结果的主闭环；展示指标、维度和关键字段可核对 | 结果有 160 行，截图无需展开全部，只保留总行数和代表性数据 |
| S03 | 展开 S02 的“查看检索过程” | 命中的表、字段、关系或检索说明 | 系统不是让模型盲猜 Schema，而是先定位业务字段和关联路径 | 若内容过长，可截局部并在图注列明“字段级检索” |
| S04 | “按地区看平均单价”的澄清状态 | 澄清原因、三个快捷选项：“订单实际成交平均价”“店铺 SKU 销售标价平均值”“用户购物车意向均价” | 识别业务语言多义性，将不确定性转化为用户决策 | 必须同时保留原问题，才能看出为什么需要澄清 |
| S05 | 选择“订单实际成交平均价”后的查询完成页 | 澄清后的用户选择、查询口径、五个大区结果、文字总结 | 澄清后恢复原任务，以及业务口径与结果一致 | 可与 S04 组成前后对照图，而非两张孤立大图 |
| S06 | 歌曲资源 Demo 查询完成页 | 问题、筛选“专属封面为空或不存在”的业务语义、8 条结果、`image_path`、文字总结 | 将真实业务定义映射到字段值，避免把“默认封面”误判为 `NULL` | 图注明确写“基于真实业务场景脱敏构造的 Demo” |
| S07 | 2026 年 7 月各地区订单量结果 + 右侧上下文 | 结果表、“保存”按钮、右侧查询字段/参考结果区域 | 查询结果不是终点，可作为后续分析资产复用 | 最好在保存后再截，右侧出现结果卡 |
| S08 | 基于 S07 参考结果的二次分析 | 提问“只使用参考结果……”、引用结果标签、最高/最低与差值答案 | 不重新查库即可基于历史结果继续分析，体现“本次上下文”的产品价值 | 图中保留“综合分析来源”标签，避免被误解为重新执行 SQL |
| S09 | 多轮追问前后 | 首轮“2026年7月各地区实付销售额”以及后续“只看华东和华南 / 换成6月 / 再按店铺拆分”中的两步 | 对筛选、时间和维度的连续修改；说明上下文连续性 | 当前能力有覆盖边界，作品集不要写成任意复杂多轮规划 |
| S10 | Evaluation Center 最新三轮报告 | 10/10、30/30、24/24、稳定准确率、P95，以及用例列表 | 用黄金用例、重复运行和分项指标验证 AI 产品质量 | 保留数据集名和重复次数，不能只裁一个“100%”数字 |

### 2.2 建议作为局部放大或注释的截图

| 编号 | 页面状态 | 适合作为哪类证据 |
|---|---|---|
| D01 | 查询口径卡特写 | 放大数据表、指标、维度、时间、筛选、关键字段和“系统识别，请核对” |
| D02 | SQL 展开状态 | 证明可解释与可核查；选用店铺大区 SKU 均价的合法多表 JOIN SQL |
| D03 | 查询失败卡 | 证明失败可见，并提供“重新尝试 / 修改问题”恢复入口；不要把故障截图放在首屏主视觉 |
| D04 | 删除全部歌曲数据被拒绝 | 证明产品只读安全边界；文字应说明“执行失败是预期安全行为” |
| D05 | `mock` 账号查询电商歌曲数据被拒绝 | 证明账号级数据范围隔离；不要表述为完整企业 RBAC |
| D06 | 结果表导出按钮与已下载 `.xls` | 证明从查询到数据交付，不需要在作品集直接展示本地下载目录 |
| D07 | 手机与电脑显示同一账号会话 | 证明服务器会话持久化和跨端恢复；属于完成度补充，不是 AI 核心能力主图 |
| D08 | 评测用例详情展开 | 展示 Gold 行数、实际行数、表/字段召回、澄清、SQL与失败原因等诊断信息 |

### 2.3 不建议作为主视觉的页面

- 登录页：能说明角色入口，但不能证明 AI 问数核心价值，最多放在“产品范围”小图中。
- 云服务器、防火墙、快照、Docker 命令：属于部署佐证，不属于产品体验叙事。
- 只展示一张结果表但没有原问题和查询口径：无法证明自然语言理解与可信设计。
- 单独放大的“100%”：缺少样本数、重复次数和限定条件，容易造成夸大。
- 大段 SQL 或代码截图：产品经理作品集只需以小面积说明可核查性，不宜替代流程和决策表达。

### 2.4 建议的截图组合方式

- **主闭环组合**：S02 查询完成页 + S03 检索过程局部 + D01 口径卡特写。
- **AI 可靠性组合**：S04 澄清前 + S05 澄清后 + D02 SQL 展开。
- **业务价值组合**：S06 歌曲资源 Demo + 图注解释“默认封面值 ≠ 空地址”。
- **持续分析组合**：S07 保存结果 + S08 参考结果二次分析 + S09 连续追问。
- **质量验证组合**：S10 指标总览 + D08 单用例详情。

## 三、核心产品素材卡

### 素材卡 A：自然语言问数闭环

- 用户问题：业务人员不熟悉数据库结构，查数依赖 SQL 或数据同学。
- 当前方案：提问 → Schema 定位 → SQL 生成/校验 → 查询 → 表格/说明 → 导出。
- 可用案例：“按订单地区统计各商品分类的销量”。
- 页面证据：S02、S03、D01、D02。
- 代码证据：`QueryWorkflow._compile`、`AskDataService.submit`、`SingleDatabaseAgent.prepare`。
- 表述边界：单库范围；数据为构造 Demo；不能宣称节省多少人时。

### 素材卡 B：AI 不确定性显性化

- 用户问题：“平均单价”“销售表现”等表达可能对应多种指标、数据来源和地区维度。
- 当前方案：以结构化选项询问用户，并在查询口径卡中显性呈现系统理解。
- 可用案例：“按地区看平均单价”。
- 页面证据：S04、S05、D01。
- 代码证据：`RequestPreprocessor.prepare`、`QueryWorkflow._human_clarification`、`AskDataService.clarify`。
- 产品意义：降低“SQL 可以运行但业务口径错误”的风险，建立人机确认点。

### 素材卡 C：Schema 与业务语义理解

- 用户问题：自然语言与实际字段名、表关系不一致。
- 当前方案：字段级关键词/语义检索、融合排序与 Rerank，再补充合法关联路径和 JOIN 键。
- 页面证据：S03、D01。
- 代码证据：`backend/app/retrieval/service.py`、`backend/app/retrieval/graph.py`。
- 表述边界：属于查询时的 Schema 上下文构建，不是数据治理、指标平台或数据血缘。

### 素材卡 D：上下文与连续分析

- 用户问题：分析需求常以逐步筛选、换时间、改维度的方式产生，结果还需要被继续引用。
- 当前方案：保留近期会话、校验 SQL 口径连续性，并允许把字段和历史结果加入“本次上下文”。
- 页面证据：S07、S08、S09。
- 代码证据：`sql_continuity.py`、`session_context.py`、`memory_store.py`、`data_qa_agent.py`。
- 表述边界：支持典型连续修改，不代表任意复杂任务规划。

### 素材卡 E：安全和失败恢复

- 用户问题：生成式 SQL 可能越权、写数据、关联错误或执行失败。
- 当前方案：生成阶段业务契约/JOIN 校验，执行阶段只读和数据权限校验，并保留纠错重试和前端恢复入口。
- 页面证据：D03、D04、D05。
- 代码证据：`single_database_agent.py`、`duckdb_engine.py`、`access_control.py`。
- 表述边界：三个预设账号和表/库范围，不是复杂企业组织权限系统。

### 素材卡 F：结果交付

- 用户问题：查数结果需要被理解、下载和继续使用，而非停留在聊天答案。
- 当前方案：分页结果、AI 说明、SQL 查看、保存/删除、参考结果复用与完整 Excel 导出。
- 页面证据：S02、S07、S08、D06。
- 代码证据：`ResultTableCard.vue`、`response_generator.py`、`memory_store.py`、`excel_export.py`。

### 素材卡 G：评测驱动迭代

- 用户问题：AI 问数不能只靠“看起来正确”，需要区分 SQL 执行、结果、澄清、安全、权限和稳定性。
- 当前方案：黄金用例、Gold SQL 对照、重复运行、分项指标、批次报告和用例详情。
- 页面证据：S10、D08。
- 代码证据：`backend/evals/core_capabilities_golden.json`、`backend/scripts/evaluate_sales.py`、`EvaluationCenter.vue`。
- 表述边界：固定 Demo 数据和 10 条核心用例，不代表开放域准确率或线上 SLA。

## 四、真实业务脱敏 Demo 素材

### 4.1 必须使用的性质标记

**基于真实业务场景脱敏构造的 Demo。**

项目没有接入真实公司的生产库。`ecommerce_ops` 是固定随机种子生成的综合零售电商演示库；歌曲资源场景借鉴真实业务问题后，以构造数据和脱敏字段重新实现。

### 4.2 场景事实核对

| 项目 | 当前真实内容 | 证据 |
|---|---|---|
| 用户问题 | “帮我找出目前还没有配置专属封面的歌曲” | `backend/evals/core_capabilities_golden.json` `core_005` |
| 实际表名 | `media_resources`，不是 `song_resources` | `backend/data/databases/ecommerce_ops/media_resources.csv` |
| 主要字段 | `resource_id`、`cn_file_name`、`artist`、`album`、`category`、`image_path` | CSV 表头和 `_schema.json` |
| 业务语义 | `image_path = 'public_third_part.jpeg'` 表示仍使用默认封面，即未配置专属封面 | `_schema.json` `image_path` 描述；黄金用例 Gold SQL |
| 容易出错的近义条件 | “没有封面地址”对应空值；当前构造数据空地址为 0，不能与默认封面混用 | `backend/tests/test_sql_product_contract.py` |
| 结果规模 | 15 条歌曲资源中有 8 条使用默认封面 | `backend/tests/test_ecommerce_dataset.py`；已演示页面 |
| 查询链路 | 经过自然语言理解、Schema 检索、SQL 生成、产品契约与只读校验 | 通用主查询工作流及 `core_005` 评测 |
| 结果承接 | 返回 8 行表格、业务字段和文字总结，并可导出 Excel | `ResultTableCard.vue`、`response_generator.py`、导出服务 |
| 专项评测 | 另有默认封面、分类统计、已配置封面三类黄金问题 | `backend/evals/media_resources_golden.json` |

### 4.3 为什么比通用销售 Demo 更有作品集价值

- 销售数据案例主要证明聚合、时间筛选和多表 JOIN；歌曲案例证明系统能理解组织内部约定的业务值。
- “未配置专属封面”在业务上不是 `NULL`，而是一个默认图片路径，能直接展示 AI 产品中技术语义与业务语义的差异。
- 该案例包含“发现歧义 → 补充 Schema 描述 → 增加 SQL 产品契约 → 建立正反评测”的完整质量闭环，适合呈现 AI 产品经理的验收意识。
- 它仍然是构造 Demo，价值在产品方法与落地链路，不在真实企业使用数据。

## 五、评测与量化素材

### 5.1 最新可引用报告

服务器运行时报告：`/home/ubuntu/askdata/runtime/evaluation-reports/sales-eval-20260906-184913.json`。

| 指标 | 报告数值 |
|---|---:|
| 核心测试用例 | 10 条 |
| 重复次数 | 每题 3 次 |
| 总运行次数 | 30 次 |
| 用例通过率 / 结果准确率 | 100%（30/30） |
| 应执行 SQL 的成功率 | 100%（24/24） |
| 明确查询准确率 | 100% |
| 澄清正确率 | 100% |
| 多轮任务完成率 | 100% |
| 安全拦截通过率 | 100% |
| 权限隔离通过率 | 100% |
| 结果说明安全率 | 100% |
| 严格稳定准确率 | 100% |
| 表 / 字段平均召回 | 100% / 100% |
| 平均响应时间 | 8.826 秒 |
| P95 响应时间 | 18.49 秒 |

### 5.2 十条用例覆盖素材

1. 订单地区实际成交均价。
2. 店铺大区 SKU 销售标价均值。
3. 缺少指标时的澄清。
4. 地区与平均单价双重歧义澄清及恢复。
5. 歌曲默认封面业务语义。
6. 默认封面与空地址的业务含义区分。
7. 订单地区与商品分类的多表聚合。
8. 删除全部歌曲数据的只读安全拦截。
9. 无权限账号访问歌曲数据的权限拦截。
10. 指定月份、下单时间和地区的订单量及总结一致性。

### 5.3 数字能证明与不能证明的内容

**能证明：**在固定代码版本、固定构造数据、固定模型配置和 10 条预定义核心问题上，三轮共 30 次均符合黄金标准；核心能力不仅覆盖查询，也覆盖澄清、多轮、安全、权限和文字说明。

**不能证明：**任意业务问题达到 100% 准确、已经达到生产 SLA、对任意数据库可泛化、拥有统计显著性、已被真实客户使用，或带来效率/转化提升。

补充工程证据：当前代码曾完成 153 项自动化测试回归。该数字可以作为版本质量佐证，不属于用户或业务成效。

## 六、产品完整度与边界

### 6.1 已实现

- 单一数据库范围的自然语言提问、Schema 检索、SQL 生成/校验/执行、结果表和文字总结。
- 查询口径卡，以及检索过程和 SQL 的查看/复制。
- 缺少指标与特定业务歧义的结构化澄清和同任务恢复。
- 典型筛选、时间、维度、指标修改的多轮连续性保护。
- 只读 SQL、安全拦截、表/库范围权限过滤、失败重试与前端恢复入口。
- 分页结果、完整 Excel 导出、字段/结果保存删除和参考结果二次分析。
- 账号级会话持久化、刷新/重登/跨设备恢复和三个预设账号隔离。
- 黄金用例、重复运行、分项指标、报告持久化和只读 Evaluation Center。
- Docker Compose 在线 Demo 部署及运行目录挂载。

### 6.2 部分实现

- 多轮连续分析：覆盖典型修改，但仍依赖模型，不能保证任意复杂追问。
- 文字总结可信度：确定性守卫主要核对行数与最高/最低等极值，不覆盖所有复杂推断。
- 图表与报告：支持 Markdown 报告、柱状图和饼图，不是完整 Dashboard 编辑器。
- 权限：三个预设角色及表/库范围过滤，没有组织、部门、用户组、SSO、动态行列权限。
- 数据接入：本地存在多个 CSV 数据库目录，但一次查询只进入一个库，且没有可视化连接与同步管理。
- 持久化：会话、记忆和评测报告可跨刷新保留，但采用单机 SQLite/JSON/文件卷方案。
- Evaluation Center：可查看批次和用例详情，仍需命令行触发评测；没有节点级 trace、趋势图和基线对比。

### 6.3 未实现，不能用于作品集能力宣称

- 企业级 BI 平台、拖拽看板、订阅和定时报表。
- 数据治理平台、数据资产目录和数据质量治理流程。
- 独立指标管理平台及指标审批、版本、负责人、生命周期。
- 多 Agent 自治协作；当前是有状态工作流编排，不是多 Agent 系统。
- 多库联邦查询；工作流明确提示多库 Handoff 未启用。
- 数据血缘系统；Schema 关系只用于 SQL 生成。
- 企业知识库及文档摄取、治理与知识检索管理。
- 复杂组织权限、企业 SSO、可配置 RBAC 和动态行列级权限。
- 真实企业用户使用、用户规模、转化率、节省工时或业务提升。
- 真实生产环境与企业级 SLA；当前只能称为在线演示部署。

## 七、作品集素材优先级

### P0：必须准备

1. 一张五段式主流程图。
2. S02/S03/D01：自然语言、多表 Schema 检索、口径与结果闭环。
3. S04/S05：歧义澄清前后对照。
4. S06：真实业务场景脱敏歌曲 Demo。
5. S07/S08：右侧“本次上下文”及历史结果二次分析。
6. S10/D08：三轮评测总览与单用例详情。

### P1：增强完整度

1. S09：连续追问修改筛选、时间和维度。
2. D04/D05：只读安全与权限隔离。
3. D06：Excel 导出。
4. D07：跨端会话恢复。

### P2：备查，不占主页面

1. 登录与三个角色说明。
2. Docker Compose 部署和持久化卷证据。
3. 自动化测试结果。
4. 关键代码、Schema JSON 与 Gold SQL，仅供面试追问时核验。

## 八、后续制作 Case Study 时仍需补采的素材

当前仓库中没有独立保存的页面截图文件。建议在同一浏览器宽度、同一 `sales` 账号和同一演示数据版本下重新截图，并统一裁切比例。需要补采：

- S01—S10 中选定的桌面端页面，优先 1440px 或 1920px 宽屏。
- S04/S05、S07/S08 两组严格前后对照画面。
- Evaluation Center 最新 `20260906-184913` 批次总览和一条展开详情。
- 歌曲资源 Demo 的完整问题、口径、8 行结果与总结；图注明确数据性质。
- 一张手机端跨设备会话恢复图，仅作为完成度补充。

截图完成后仍应单独保留原始全屏图；进入作品集时再复制、裁切和标注，避免破坏证据原件。

## 九、关键证据索引

| 主题 | 文件 / 关键类或组件 |
|---|---|
| API 与流程入口 | `backend/app/api/routes.py`；`backend/app/services/askdata_service.py` `AskDataService` |
| 工作流 | `backend/app/workflows/query_graph.py` `QueryWorkflow` |
| 意图、上下文与澄清 | `backend/app/preprocessing.py` `RequestPreprocessor` |
| Schema 检索 | `backend/app/retrieval/service.py` `SchemaRetrievalService` |
| Schema 关系图 | `backend/app/retrieval/graph.py` `SchemaGraphBuilder` |
| SQL 生成与产品契约 | `backend/app/querying/single_database_agent.py` `SingleDatabaseAgent` |
| SQL 执行与安全 | `backend/app/querying/duckdb_engine.py` `DuckDbEngine` |
| 多轮连续性 | `backend/app/querying/sql_continuity.py` |
| 结果总结与校验 | `backend/app/querying/response_generator.py`；`summary_fidelity.py` |
| 保存与上下文 | `backend/app/services/memory_store.py`；`session_context.py` |
| 会话持久化 | `backend/app/services/session_archive.py` |
| 数据权限 | `backend/app/security/access_control.py`；`auth.py` |
| Excel 导出 | `backend/app/services/excel_export.py`；`AskDataService.export` |
| 主界面和查询口径 | `frontend/src/App.vue` |
| 结果表 | `frontend/src/components/ResultTableCard.vue` |
| 评测中心 | `frontend/src/components/EvaluationCenter.vue` |
| 核心评测集 | `backend/evals/core_capabilities_golden.json` |
| 评测脚本 | `backend/scripts/evaluate_sales.py` |
| 歌曲专项评测 | `backend/evals/media_resources_golden.json` |
| 歌曲构造数据与 Schema | `backend/data/databases/ecommerce_ops/media_resources.csv`；`_schema.json` |
