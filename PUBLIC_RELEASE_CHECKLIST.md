# GitHub 公开版发布检查

## 已保留

- 前后端核心源码
- 构造的 `askdata_mock` 与 `ecommerce_ops` 演示数据
- Schema 元数据与检索索引
- 核心测试与黄金评测集
- Dockerfile、Docker Compose 和环境变量模板
- 产品审计与 Case Study 素材文档

## 已排除

- `backend/.env`、`backend/.env.production`、`frontend/.env`
- API Key、Token、私钥和线上服务器凭据
- 会话数据库、保存结果和用户运行数据
- 历史评测报告、服务器日志和本地日志
- `node_modules`、`dist`、`__pycache__`、`.pyc`
- 部署压缩包和临时目录

## 已做的公开版差异

- `backend/app/security/auth.py` 不再包含可登录的默认密码；三个 Demo 账号必须通过环境变量设置密码。
- 测试使用独立的 `test-*-password`，不对应任何线上账号。
- Docker Compose 默认暴露 `8080`，避免直接占用宿主机的 80 端口。
- README 明确构造数据、评测数字和产品能力边界。

这些差异只存在于 `github-public/`，没有修改原项目业务代码或部署配置。

## 验证结果

- 后端：153 项自动化测试通过。
- 前端：TypeScript 检查和 Vite 生产构建通过。
- 敏感扫描：未发现真实 API Key、私钥、线上地址或原 Demo 默认密码。
- 目录扫描：未保留日志、数据库运行文件、缓存、构建产物或部署压缩包。

## 上传前仍需人工确认

- 确认公开仓库名称、简介和是否加入在线 Demo 地址。
- 决定是否添加开源许可证；未添加许可证时，默认不授予他人复制、修改或再分发权限。
- 对页面截图再次检查账号、IP、浏览器收藏和个人信息。
- 在 GitHub 创建仓库后，先检查首次提交的文件清单，再执行推送。

