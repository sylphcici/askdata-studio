# Ubuntu 部署说明

## 1. 安装 Docker

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 unzip
sudo systemctl enable --now docker
```

## 2. 上传并解压项目

将部署压缩包上传到 `/home/ubuntu/`，然后执行：

```bash
cd /home/ubuntu
unzip askdata-deploy.zip -d askdata
cd askdata
mkdir -p runtime
cp backend/.env.production.example backend/.env.production
chmod 600 backend/.env.production
nano backend/.env.production
```

在编辑器中填写真实模型 API Key、Workspace 地址和三个演示账号密码。保存后退出。

## 3. 构建并启动

```bash
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 backend
```

健康检查：

```bash
curl http://127.0.0.1/api/health
```

浏览器访问服务器公网 IP。仅需在腾讯云防火墙开放 TCP 80；后端 8000 不对公网开放。

## 4. 更新与回滚

更新代码后重新构建：

```bash
sudo docker compose up -d --build
```

查看日志：

```bash
sudo docker compose logs -f --tail=100
```

停止服务：

```bash
sudo docker compose down
```

`runtime/` 保存会话和收藏记录。重新构建容器不会删除；迁移或到期前应备份该目录与 `backend/.env.production`。
