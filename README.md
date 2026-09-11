# AskData Studio

面向不熟悉 SQL 的运营与业务分析人员的单库智能问数工作台。用户可以使用自然语言提出数据问题，核对系统识别的查询口径，并获得只读 SQL 查询结果、文字说明与 Excel 导出。

> 这是用于产品作品集展示的公开版代码。仓库中的电商数据均为固定规则生成的模拟数据；歌曲资源案例是**基于真实业务场景脱敏构造的 Demo**，不包含真实公司生产数据、真实用户记录或商业指标。

## 核心能力

- 自然语言提问到 Schema 检索、单库 SQL 生成、校验、执行和结果解释的完整链路
- 数据表、指标、维度、时间、筛选条件和关键字段的查询口径核对
- 信息不足时的结构化澄清与原任务恢复
- 典型筛选、时间、指标和维度修改的连续分析
- SQL 查看、分页结果、文字总结、结果保存和 Excel 导出
- 只读 SQL、危险操作拦截和预设账号数据范围隔离
- 服务端会话历史和保存结果持久化
- 覆盖查询、澄清、多轮、安全、权限和总结一致性的回归评测

## 演示数据

公开版保留两组构造数据：

- `askdata_mock`：小型基础演示数据。
- `ecommerce_ops`：综合零售电商构造数据，用于多表查询、权限与业务语义演示。

歌曲资源表的 `image_path = 'public_third_part.jpeg'` 表示仍使用系统默认封面。它与“封面地址为 `NULL` 或空字符串”是不同业务口径。

## 快速启动

### Docker Compose

1. 复制环境变量模板：

   ```bash
   cp backend/.env.production.example backend/.env
   ```

2. 编辑 `backend/.env`，填写自己的模型、Embedding 和 Rerank 服务配置，并修改三个 Demo 账号密码。

3. 启动：

   ```bash
   docker compose up --build
   ```

4. 打开 `http://localhost:8080`。

`runtime/` 用于保存本机的会话、结果记忆和评测报告，已被 `.gitignore` 排除。

### 本地开发

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

前端：

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## 回归评测

核心评测集位于 `backend/evals/core_capabilities_golden.json`。配置模型服务后可运行：

```bash
cd backend
python scripts/evaluate_sales.py --dataset evals/core_capabilities_golden.json --repeat 3
```

当前项目曾在固定代码、固定构造数据和固定模型配置下完成 10 条核心用例 × 3 轮、共 30 次回归。该结果只证明预定义核心场景的版本稳定性，不代表任意问题准确率、生产 SLA 或真实用户效果。

## 项目边界

当前实现是可在线演示的单库智能问数 MVP，不是：

- 企业级 BI 或数据治理平台
- 多 Agent 自治协作系统
- 多库联邦查询系统
- 数据血缘或企业知识库
- 复杂组织权限、SSO 或动态行列级权限系统
- 已被真实企业采用的生产系统

## 目录

```text
backend/app/                         核心服务与问数工作流
backend/data/databases/              构造演示数据及 Schema
backend/evals/                       黄金评测集
backend/scripts/evaluate_sales.py    回归评测脚本
backend/tests/                       自动化测试
frontend/src/                        Vue 产品界面
askdata_resume_audit.md              简历事实审计
askdata_portfolio_materials.md       Case Study 素材清单
```

## 安全提示

- 不要提交实际 `.env`、API Key、Token、会话数据库、保存结果、日志或评测运行报告。
- 公开部署前必须设置新的 `ASKDATA_ADMIN_PASSWORD`、`ASKDATA_SALES_PASSWORD` 和 `ASKDATA_MOCK_PASSWORD`。
- 如果密钥曾进入 Git 历史，仅删除当前文件并不安全，应立即轮换密钥并清理历史。
- 本仓库暂未附加开源许可证；在明确授权范围前，默认不授予复制、修改或再分发许可。

