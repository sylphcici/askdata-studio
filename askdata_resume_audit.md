# AskData Studio：面向产品经理 / AI 产品经理简历的项目总结审计

> 审计口径：仅依据当前工作区代码、数据文件、自动化测试，以及本次部署过程中已展示的服务器评测报告。README 与产品设想不作为能力成立的单独证据。本文中的“已实现”表示代码存在并经过相应验证，不等于已经被真实企业客户采用或达到生产级 SLA。

## 一、一句话定位

**AskData Studio 是面向不熟悉 SQL 的运营与业务分析人员的单库智能问数工作台，通过自然语言完成业务口径澄清、字段级 Schema 定位、只读 SQL 查询、结果解释与复用，并以权限隔离和可回归评测降低 AI 查数的不确定性。**

这个定位比“企业 BI 平台”准确：当前产品已经形成问数闭环，但数据源是本地 CSV/DuckDB 演示库，权限模型为三个预设账号，且跨数据库联合查询尚未启用。因此简历可写“智能问数工作台/产品 Demo”，不宜写“企业级 BI 平台”。

核心证据：

- 工作流编排与路由：[backend/app/workflows/query_graph.py](backend/app/workflows/query_graph.py#L29) `QueryWorkflow`。
- 自然语言查询入口：[backend/app/api/routes.py](backend/app/api/routes.py#L173) `query`。
- 单库 SQL 智能体：[backend/app/querying/single_database_agent.py](backend/app/querying/single_database_agent.py#L37) `SingleDatabaseAgent.prepare`。
- 只读执行与权限检查：[backend/app/querying/duckdb_engine.py](backend/app/querying/duckdb_engine.py#L112) `DuckDbEngine._validate_sql`。
- 当前多库边界：[backend/app/workflows/query_graph.py](backend/app/workflows/query_graph.py#L438) `_run_multi_database` 明确返回“多库 Handoff 尚未启用”。

## 二、当前真实产品链路

### 2.1 主查询链路

```text
自然语言提问
→ 意图识别与上下文改写
→ 字段级 Schema 混合检索
→ Schema 图与合法关联路径补全
→ 必要时结构化澄清
→ 单库 SQL 生成
→ SQL 产品契约、连续性与只读权限校验
→ DuckDB 执行
→ 分页结果表
→ AI 结果说明及确定性一致性检查
→ 连续追问 / 保存为参考结果
→ 完整结果 Excel 导出
```

| 环节 | 实现判断 | 当前实现与证据 |
|---|---|---|
| 自然语言提问 | 已实现 | 前端 `submit` 调用查询 API，并携带当前会话与右侧上下文：[frontend/src/App.vue](frontend/src/App.vue#L538)。后端入口：[backend/app/api/routes.py](backend/app/api/routes.py#L173)。 |
| 意图与参数识别 | 已实现 | 预处理器区分 `database_query`、`data_qa`、`direct_response`，生成可独立理解的 `standalone_query` 与检索词：[backend/app/preprocessing.py](backend/app/preprocessing.py#L49) `RequestPreprocessor.prepare`。 |
| Schema 检索 | 已实现 | BM25 与向量召回经 RRF 融合，再调用 Rerank 并按阈值选择字段：[backend/app/retrieval/service.py](backend/app/retrieval/service.py#L91) `retrieve`，尤其是 L121-L178。 |
| 表关系补全 | 已实现 | 根据已召回字段所在表寻找关系路径，并补充关联键、主键和必要展示字段：[backend/app/retrieval/graph.py](backend/app/retrieval/graph.py#L101) `SchemaGraphBuilder.build`。 |
| 必要时澄清 | 已实现 | 预处理阶段可因缺少指标或业务口径产生结构化选项；LangGraph 通过 `interrupt` 暂停并恢复任务：[backend/app/preprocessing.py](backend/app/preprocessing.py#L137)、[backend/app/workflows/query_graph.py](backend/app/workflows/query_graph.py#L240)。 |
| SQL 生成 | 已实现（单库） | 模型接收 Schema 图、关联关系、用户确认字段和上一轮 SQL，通过受限工具协议生成并执行查询：[backend/app/querying/single_database_agent.py](backend/app/querying/single_database_agent.py#L95)。 |
| SQL 校验 | 已实现 | 生成阶段校验业务结果契约与 JOIN；执行层只接受单条 `SELECT/WITH`，拒绝写入、管理语句、`SELECT *`、未知表和越权表：[backend/app/querying/single_database_agent.py](backend/app/querying/single_database_agent.py#L444)、[backend/app/querying/duckdb_engine.py](backend/app/querying/duckdb_engine.py#L112)。 |
| 查询执行 | 已实现 | DuckDB 将单个数据库目录中的 CSV 注册为只读视图，页面查询最多返回 200 行并记录总行数：[backend/app/querying/duckdb_engine.py](backend/app/querying/duckdb_engine.py#L33)。 |
| 结果表格 | 已实现 | 支持 10/20/50 行分页、总行数提示及导出状态：[frontend/src/components/ResultTableCard.vue](frontend/src/components/ResultTableCard.vue#L26)。 |
| AI 结果说明 | 已实现但校验范围有限 | 模型生成标题与说明；确定性检查覆盖返回行数及数值列最高/最低结论，不是任意自然语言事实校验：[backend/app/querying/response_generator.py](backend/app/querying/response_generator.py#L28)、[backend/app/querying/summary_fidelity.py](backend/app/querying/summary_fidelity.py#L20)。 |
| 连续追问 | 已实现，覆盖有限 | 会话保留近期结果与上下文；SQL 连续性守卫识别筛选、时间、维度、指标修改并防止无关口径漂移：[backend/app/querying/sql_continuity.py](backend/app/querying/sql_continuity.py#L20)、[backend/app/services/session_context.py](backend/app/services/session_context.py#L107)。 |
| Excel 导出 | 已实现 | 后端重新执行已验证 SQL，最多导出 50,000 行 SpreadsheetML；前端下载 `.xls`：[backend/app/services/askdata_service.py](backend/app/services/askdata_service.py#L185)、[backend/app/services/excel_export.py](backend/app/services/excel_export.py#L10)、[frontend/src/components/ResultTableCard.vue](frontend/src/components/ResultTableCard.vue#L56)。 |

### 2.2 产品承接链路

- 查询口径卡真实展示数据表、指标、维度、时间范围、筛选条件和关键字段，并标注“系统识别，请核对”：[frontend/src/App.vue](frontend/src/App.vue#L994)。
- 用户可展开检索过程和 SQL，查询失败后可“重新尝试”或“修改问题”：[frontend/src/App.vue](frontend/src/App.vue#L969)、[frontend/src/App.vue](frontend/src/App.vue#L1027)。
- 查询结果和字段可按用户保存、删除；已保存结果可拖入右侧“参考结果”，字段可拖入“查询字段”：[frontend/src/App.vue](frontend/src/App.vue#L573)、[frontend/src/App.vue](frontend/src/App.vue#L624)、[frontend/src/App.vue](frontend/src/App.vue#L656)。
- 对话以账号为单位保存在服务器 SQLite，并由前端登录后读取；Docker 将运行数据挂载到宿主机：[backend/app/services/session_archive.py](backend/app/services/session_archive.py#L168)、[backend/app/api/routes.py](backend/app/api/routes.py#L130)、[docker-compose.yml](docker-compose.yml#L8)。

## 三、最值得写入产品经理简历的项目亮点

### 1. 形成自然语言问数的端到端闭环

产品不是只生成 SQL：已串联提问、意图判断、Schema 定位、SQL 生成与校验、执行、分页结果、结果说明、保存和导出。它解决的是业务人员必须依赖数据同学、且难以核对查询过程的问题。

证据：`QueryWorkflow._compile`（[query_graph.py](backend/app/workflows/query_graph.py#L67)）、`AskDataService.submit`（[askdata_service.py](backend/app/services/askdata_service.py#L43)）、查询结果 UI（[App.vue](frontend/src/App.vue#L1048)）。

### 2. 用字段级检索和业务语义映射降低表字段门槛

Schema 文档包含表用途、字段中文名、描述、别名、样例、数据特征和关系；检索采用关键词与语义召回、RRF 和 Rerank，并把用户在右侧明确选择的字段以高优先级纳入。其产品价值是将“用户业务表达”连接到“数据库可执行上下文”，而非要求用户记住表名字段名。

证据：[retrieval/service.py](backend/app/retrieval/service.py#L121) 混合检索、[retrieval/service.py](backend/app/retrieval/service.py#L222) 用户确认字段、[retrieval/graph.py](backend/app/retrieval/graph.py#L101) 关系路径。

### 3. 将 AI 隐式判断转化为可核对的查询口径

页面把系统识别的数据表、指标、维度、时间、筛选和关键字段显性展示，用户可检查 SQL 与检索过程。这解决了 AI 问数中“答案看起来合理，但不知道用了什么口径”的信任问题，是比单纯聊天框更有产品价值的设计。

证据：[frontend/src/App.vue](frontend/src/App.vue#L969) 检索过程、[frontend/src/App.vue](frontend/src/App.vue#L994) 查询口径、[frontend/src/App.vue](frontend/src/App.vue#L1059) SQL 查看与复制。

### 4. 信息不足时先澄清，再恢复原任务

系统对“各地区销售表现”等缺少指标的问题提供销售额、订单量、客单价选项；对“按地区看平均单价”区分订单成交价、店铺 SKU 标价和购物车意向价。选择后使用同一任务状态继续执行，减少模型自行补口径造成的业务错误。

证据：[preprocessing.py](backend/app/preprocessing.py#L137) 指标澄清、[preprocessing.py](backend/app/preprocessing.py#L245) 地区/均价确定性守卫、[askdata_service.py](backend/app/services/askdata_service.py#L110) `clarify`。

### 5. 连续追问中保护既有口径

预处理器将依赖上文的问题改写成独立查询；SQL 连续性守卫支持“只看华东和华南”“换成 6 月”“再按店铺拆分”等筛选、时间和维度变更，并检查未要求修改的指标、数据源、时间字段和筛选条件是否被意外改变。

证据：[preprocessing.py](backend/app/preprocessing.py#L60) 上下文继承/覆盖/清除规则、[sql_continuity.py](backend/app/querying/sql_continuity.py#L20)、对应测试 [test_sql_continuity.py](backend/tests/test_sql_continuity.py#L16)。

边界：这些操作有规则和单元测试支持，但自然语言改写仍依赖模型，不能表述为“支持任意复杂连续分析”或“所有追问均稳定正确”。

### 6. 用分层防护处理错误与不确定性

产品同时提供生成阶段的字段/JOIN/结果契约校验、执行阶段的只读与权限校验、工具调用纠错重试、模型请求重试，以及前端的失败归因、重新尝试和修改问题入口。其价值是让失败可见、可恢复，而不是静默返回错误数据。

证据：[single_database_agent.py](backend/app/querying/single_database_agent.py#L140) 工具调用循环、[duckdb_engine.py](backend/app/querying/duckdb_engine.py#L112) 只读校验、[model_client.py](backend/app/model_client.py#L136) 请求重试、[App.vue](frontend/src/App.vue#L508) 失败提示与恢复。

### 7. 让查询结果可以交付和复用

结果不仅在表格中分页展示，还可生成文字说明、导出完整 Excel、保存/删除；用户可将字段作为 SQL 生成约束，或将历史结果作为二次分析上下文。实际演示已验证“保存地区订单量结果 → 新对话引用 → 计算最高、最低及差值”的链路。

证据：[memory_store.py](backend/app/services/memory_store.py#L11)、[session_context.py](backend/app/services/session_context.py#L220) 参考结果上下文、[data_qa_agent.py](backend/app/querying/data_qa_agent.py#L36)、右侧上下文 [App.vue](frontend/src/App.vue#L1127)。

### 8. 建立面向 AI 问数风险的回归评测

评测数据集不只检查 SQL 能否运行，还分别检查标准结果、表/字段召回、澄清、多轮完成、安全拦截、权限隔离和结果说明一致性；支持重复运行并计算严格稳定准确率。这体现了从“做出 Demo”走向“定义质量标准并持续回归”的 AI 产品意识。

证据：[backend/evals/core_capabilities_golden.json](backend/evals/core_capabilities_golden.json#L1)、[evaluate_sales.py](backend/scripts/evaluate_sales.py#L289) 单用例评测、[evaluate_sales.py](backend/scripts/evaluate_sales.py#L464) 指标汇总、[EvaluationCenter.vue](frontend/src/components/EvaluationCenter.vue#L132) 页面。

## 四、评测体系审计

### 4.1 当前真实实现

- 黄金测试集以人工 SQL 结果为标准，覆盖明确查询、两类澄清、真实业务语义 Demo、多表关联、只读安全、权限隔离和时间查询，共 10 个核心用例：[core_capabilities_golden.json](backend/evals/core_capabilities_golden.json#L1)。
- SQL 执行成功率只统计“应该执行 SQL”的查询，安全与权限拦截用例不错误计入分母：[evaluate_sales.py](backend/scripts/evaluate_sales.py#L464)。
- 结果准确率通过实际结果与 Gold SQL 结果比较；表/字段召回通过实际 Schema 图与期望集合比较：[evaluate_sales.py](backend/scripts/evaluate_sales.py#L343)。
- 结果说明检查包括原始说明忠实性与最终展示说明安全性；当前确定性守卫主要覆盖行数及极值结论：[summary_fidelity.py](backend/app/querying/summary_fidelity.py#L20)。
- 页面支持按日期、批次、全部/未通过筛选，展示每轮用例、结果行数、失败归因、实际澄清和生成 SQL：[EvaluationCenter.vue](frontend/src/components/EvaluationCenter.vue#L27)、[EvaluationCenter.vue](frontend/src/components/EvaluationCenter.vue#L174)。
- 评测任务仍需在后端脚本发起，评测中心是只读报告页；页面没有展示每个 LangGraph 节点或全部 `execution_log`，因此不能写“支持分阶段执行链路诊断”。页面也用 `case_count >= 20` 判断“全量”，10 条核心集会被标为“调试”批次：[evaluation_reports.py](backend/app/services/evaluation_reports.py#L19)。

### 4.2 可引用的最新核心评测数字

部署服务器上的报告 `sales-eval-20260906-184913.json`（运行时路径：`/home/ubuntu/askdata/runtime/evaluation-reports/`）记录：

| 指标 | 数值 |
|---|---:|
| 核心样本 | 10 条 |
| 每题重复 | 3 次 |
| 总运行次数 | 30 次 |
| 结果准确率 | 100%（30/30） |
| 应执行 SQL 的成功率 | 100%（24/24） |
| 明确查询准确率 | 100% |
| 澄清正确率 | 100% |
| 多轮任务完成率 | 100% |
| 安全拦截通过率 | 100% |
| 权限隔离通过率 | 100% |
| 结果说明安全率 | 100% |
| 严格稳定准确率 | 100% |
| 表/字段平均召回 | 100% / 100% |
| 平均响应时间 / P95 | 8.826 秒 / 18.49 秒 |

另外，本次审计前对当前代码执行了 `unittest discover`，153 项自动化测试通过；这能作为开发回归证据，但不应包装成业务效果指标。

这些数字**可以证明**：在固定版本、固定演示数据、固定模型配置和这 10 个预定义核心问题上，连续三轮均得到符合黄金标准的结果，且覆盖关键风险路径。

这些数字**不能证明**：对任意自然语言问题达到 100% 准确；已经服务真实企业用户；具备统计显著性；线上长期 SLA 为 100%；或能泛化到任意数据库。简历中必须写成“10 条核心用例 × 3 轮回归”，不能只写“准确率 100%”。

补充审计：权限评测用例使用 `demo_mock` 作为无权限用户，而实际 `mock` 登录映射为 `demo_analyst`；真实账号隔离另有 API 测试覆盖：[auth.py](backend/app/security/auth.py#L29)、[test_auth.py](backend/tests/test_auth.py#L11)。因此可写“实现并测试账号级数据范围隔离”，不宜把单个评测数字描述成完整企业权限认证。

## 五、真实业务脱敏 Demo 审计

### 5.1 正确标记

**基于真实业务场景脱敏构造的 Demo。**

不能写成“接入某真实公司的数据库”或“在真实公司生产库上线”。代码中的电商库由固定随机种子生成，清单显示为“星购商城综合零售电商运营”，含 51 张表、381,978 行构造数据：[backend/data/databases/ecommerce_ops/_database_manifest.json](backend/data/databases/ecommerce_ops/_database_manifest.json#L2)。歌曲资源是其中的 `media_resources` 表，而不是 `song_resources`，共有 15 条构造记录。

### 5.2 落地核对

| 核对项 | 结论 | 证据 |
|---|---|---|
| 数据模型 | 已实现 | `media_resources.csv` 包含 `resource_id`、`cn_file_name`、`artist`、`album`、`category`、`image_path` 等字段：[media_resources.csv](backend/data/databases/ecommerce_ops/media_resources.csv#L1)。 |
| Schema 描述 | 已实现 | 表被描述为“当前歌曲媒体资源主表”，业务域为内容资源运营；`image_path` 明确解释默认封面含义：[_schema.json](backend/data/databases/ecommerce_ops/_schema.json#L16137)、[_schema.json](backend/data/databases/ecommerce_ops/_schema.json#L16390)。 |
| 默认封面判断 | 已实现 | `public_third_part.jpeg` 表示仍使用默认封面、尚未配置专属封面；当前 15 条中有 8 条满足条件、空地址为 0 条。数据测试：[test_ecommerce_dataset.py](backend/tests/test_ecommerce_dataset.py#L225)。 |
| 自然语言查询 | 已实现并实际演示 | “帮我找出目前还没有配置专属封面的歌曲”进入标准问数链路；核心评测将其作为 `core_005`：[core_capabilities_golden.json](backend/evals/core_capabilities_golden.json#L74)。 |
| SQL 生成与校验 | 已实现 | Gold SQL 要求 `image_path = 'public_third_part.jpeg'`；产品契约会区分“默认封面”与“封面地址为空”，防止语义混用：[test_sql_product_contract.py](backend/tests/test_sql_product_contract.py#L89)、[test_sql_product_contract.py](backend/tests/test_sql_product_contract.py#L128)。 |
| 表格与总结 | 已实现并实际演示 | 返回 8 条、6 个业务字段的结果表，并生成与结果一致的说明；通用承接组件见 [ResultTableCard.vue](frontend/src/components/ResultTableCard.vue#L80) 与 [response_generator.py](backend/app/querying/response_generator.py#L28)。 |
| Excel 导出 | 已实现并验证 | 结果卡调用后端完整导出接口；导出会重新执行已经过验证的 SQL，而非仅导出当前分页：[askdata_service.py](backend/app/services/askdata_service.py#L185)。 |
| 专项评测 | 已实现 | `media_resources_demo_v1` 含默认封面列表、分类统计和已配置封面列表三类黄金问题：[media_resources_golden.json](backend/evals/media_resources_golden.json#L1)。 |

### 5.3 作品集价值

通用销售 Demo 证明基础聚合、筛选和多表关联；歌曲资源 Demo 进一步证明产品能把组织内部约定“未配置专属封面”映射为具体字段值，而不是机械地理解成 `NULL`。它更适合讲 AI 产品经理如何发现业务歧义、定义语义规则、构造验收用例并避免“技术正确、业务错误”。

## 六、产品完整度与边界

### 已实现

- 单一数据库范围内的自然语言到 SQL、只读执行、结果表与文字说明闭环。
- 字段级 Schema 混合检索、中文语义/别名、样例与显式表关系图。
- 缺少指标和特定高风险业务口径的结构化澄清及同任务恢复。
- 查询口径卡、检索过程、SQL 查看与复制。
- 生成阶段契约校验、JOIN 限制、执行阶段只读/未知表/越权表校验。
- 结果分页、完整 Excel 导出、结果与字段保存/删除、历史结果二次分析。
- 近期上下文、部分连续查询改写及 SQL 口径连续性保护。
- 三个预设账号的数据范围隔离，账号级对话与保存内容持久化。
- 评测脚本、黄金用例、重复运行、批次报告和只读评测中心。
- Docker Compose 部署、健康检查、运行数据与评测报告卷挂载；已在云服务器形成可访问 Demo，但不等同企业生产上线。

### 部分实现

- **多轮连续分析**：支持典型筛选、月份、维度和指标修改，但不是任意复杂对话规划，仍受模型稳定性和近期上下文窗口限制。
- **结果说明可信度**：确定性检查覆盖行数和最高/最低等极值，未覆盖所有比例、因果、趋势和复杂推断。
- **分析报告/图表**：代码支持 Markdown 报告与柱状图、饼图，但不是完整可配置仪表盘或 BI 看板系统：[data_qa_agent.py](backend/app/querying/data_qa_agent.py#L106)。
- **权限体系**：实现三个代码预设角色和表/库范围过滤，不支持组织、部门、用户组、行列级策略配置、SSO 或管理员动态授权。
- **数据接入**：可以在本地按数据库目录注册多组 CSV，但单次查询只支持一个库；没有可视化数据源连接与同步管理。
- **会话与记忆**：服务端持久化、跨端同步和账号隔离已经实现，但采用单机 SQLite/JSON，没有生命周期策略、搜索、审计导出或分布式一致性。
- **评测中心**：可看批次、指标和用例详情，但评测需命令行触发，也没有节点级 trace、趋势图、基线对比或线上反馈闭环。

### 未实现，不能写进简历

- 完整 BI 平台、拖拽式 Dashboard、订阅与定时报表。
- 企业数据治理平台、数据资产目录、数据质量治理流程。
- 独立指标管理平台：没有指标注册、版本、审批、负责人和口径生命周期。
- 多 Agent 协作系统：当前是 LangGraph 编排的单库查询与数据问答组件，不是多个自治 Agent 协作。
- 多库联邦查询：代码明确返回尚未启用。
- 数据血缘分析：当前只有用于 SQL 生成的 Schema 关系，不是字段/任务血缘系统。
- 企业知识库：保存字段、结果和会话不等于知识库，也没有文档摄取、检索管理与知识治理。
- 复杂组织权限、SSO、RBAC 配置后台、行列级动态权限。
- 真实企业用户规模、使用人数、转化率、节省工时、效率提升等业务结果。
- 已上线真实生产环境或达到企业级可用性；目前有公开云端 Demo 与持久化部署证据，只能称“在线演示部署”。

## 七、简历素材池（候选 8 条）

1. **围绕业务人员不熟悉 SQL 的查数门槛，设计自然语言提问到 Schema 定位、SQL 校验执行、结果解释与 Excel 导出的完整闭环，形成可在线演示的单库智能问数工作台。**

2. **针对业务表达与数据库字段难对齐的问题，引入字段级关键词/语义召回、融合排序与业务语义描述，将自然语言映射到相关表、字段及合法关系，为 SQL 生成提供受控上下文。**

3. **针对 AI 容易“猜口径”的风险，将数据表、指标、维度、时间、筛选条件和关键字段显性化，并提供检索过程与 SQL 核对入口，提升查询结果的可解释性与用户信任。**

4. **为信息不足场景设计结构化澄清与快捷选项，区分成交价、SKU 标价等相近业务定义，并在用户确认后恢复原任务执行，降低 SQL 可运行但业务口径错误的风险。**

5. **围绕连续分析中的口径漂移，设计上下文继承、覆盖与清除规则，并校验追问前后的指标、时间字段和筛选条件，支持典型筛选、换月和下钻场景的连续问数。**

6. **设计“查询字段约束”和“历史结果分析”两类右侧上下文，支持保存/删除字段与结果、跨对话引用及账号级持久化，让一次性查询结果可继续分析和交付。**

7. **将脱敏实习场景构造成歌曲资源 Demo，把“未配置专属封面”定义为仍使用指定默认封面，并配套 Schema 描述、SQL 契约和黄金用例，体现真实业务语义落地。**

8. **建立覆盖查询、澄清、多轮、安全、权限和说明一致性的 10 条核心评测集，连续 3 轮共 30 次全部通过，其中应执行 SQL 的查询 24/24 成功，用回归指标验证版本稳定性。**

## 八、一页产品经理简历最值得写的 3 条

### 第一条：端到端问数闭环

候选文案：

> 围绕业务人员不熟悉 SQL 的查数门槛，设计自然语言提问到 Schema 定位、SQL 校验执行、结果解释与 Excel 导出的完整闭环，形成可在线演示的单库智能问数工作台。

- **为什么选**：先让招聘方快速理解产品服务谁、解决什么问题、做到什么程度，是项目总纲。
- **证明什么**：需求抽象、流程设计、端到端落地和 Demo 交付能力。
- **与其他条关系**：覆盖产品全貌，但不展开 AI 可靠性方法和量化验证，和后两条不重复。

### 第二条：澄清与可核对口径

候选文案：

> 针对 AI 易误解业务口径的问题，将表、指标、维度、时间和关键字段显性化，并设计结构化澄清与任务恢复，区分成交价、SKU 标价等相近定义，减少“SQL 正确、业务错误”。

- **为什么选**：这是项目相较普通 Text-to-SQL Demo 最突出的 AI 产品设计。
- **证明什么**：能识别模型不确定性，并将其转化为用户可理解、可决策、可恢复的交互机制。
- **与其他条关系**：第一条讲闭环，这一条讲可靠性与信任，不重复。

### 第三条：评测驱动的质量验证

候选文案：

> 建立覆盖查询、澄清、多轮、安全、权限和说明一致性的 10 条核心评测集，连续 3 轮共 30 次全部通过，其中 24/24 次应执行 SQL 的查询成功，以回归指标验证版本稳定性。

- **为什么选**：提供可核实的结果证据，避免项目描述只有功能清单；“10 条 × 3 轮”的限定也保持事实准确。
- **证明什么**：AI 产品质量定义、验收标准设计、问题归因和迭代闭环意识。
- **与其他条关系**：前两条说明做了什么、为什么这样设计；第三条说明如何验证，不重复。

如果版面允许在项目描述前增加一句补充，可写：**“基于构造电商数据与真实业务场景脱敏 Demo 完成在线部署，未使用真实公司生产数据。”** 这能主动澄清数据性质，避免面试中因措辞产生可信度风险。
