---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: dfa59edf71882ac3e29663828f688f4a_09f1c24770bc11f1b2f55254006c9bbf
    ReservedCode1: q+FhtxWqb0ScVipYahDS60EyZvJWkvlw4a30+ajy1Vcr4a/kftGFSUOirPBEZUoNn3BfkB6uZI4kx4+YOAQ+juy/AEyizdxd3G6YKnPKra4w9wcLMKUoUP2yJ+U1RUt9VwwZM1TY7xoaa85sV12gELxiY/tckQmI24O36hhNZEltm/EmjkDx/LhkRdo=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: dfa59edf71882ac3e29663828f688f4a_09f1c24770bc11f1b2f55254006c9bbf
    ReservedCode2: q+FhtxWqb0ScVipYahDS60EyZvJWkvlw4a30+ajy1Vcr4a/kftGFSUOirPBEZUoNn3BfkB6uZI4kx4+YOAQ+juy/AEyizdxd3G6YKnPKra4w9wcLMKUoUP2yJ+U1RUt9VwwZM1TY7xoaa85sV12gELxiY/tckQmI24O36hhNZEltm/EmjkDx/LhkRdo=
---

# Canopy Docker 部署指南

## 前置条件

- Docker Engine 20.10+（[安装 Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/)）
- Docker Compose v2（Docker Desktop 已内置）

验证安装：

```bash
docker --version
docker compose version
```

## 构建镜像

在项目根目录 `/Users/cccc/Desktop/canopy` 执行：

```bash
cd /Users/cccc/Desktop/canopy
docker build -t canopy:latest .
```

构建参数说明：
- 基础镜像：`python:3.11-slim`
- 工作目录：`/app`
- 暴露端口：`8000`

## 启动服务

```bash
docker compose up -d
```

- `-d`：后台运行（detached mode）
- 容器名：`canopy`
- 数据卷挂载：`./data` → `/app/data`（数据持久化）
- 重启策略：`unless-stopped`（除非手动停止，否则自动重启）

## 查看日志

```bash
# 实时日志
docker compose logs -f

# 最近 100 行
docker compose logs --tail 100
```

## 停止服务

```bash
# 停止容器
docker compose stop

# 停止并删除容器
docker compose down

# 停止并删除容器 + 数据卷（谨慎）
docker compose down -v
```

## 环境变量

在 `docker-compose.yml` 中配置，或创建 `.env` 文件：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PYTHONUNBUFFERED` | `1` | 禁用 Python 输出缓冲 |
| `CANOPY_API_KEY` | - | 交易所 API Key |
| `CANOPY_API_SECRET` | - | 交易所 API Secret |
| `CANOPY_EXCHANGE` | `binance` | 交易所 ID |
| `CANOPY_LOG_LEVEL` | `INFO` | 日志级别 |

`.env` 示例：

```env
CANOPY_API_KEY=your_api_key_here
CANOPY_API_SECRET=your_api_secret_here
CANOPY_EXCHANGE=binance
CANOPY_LOG_LEVEL=INFO
```

然后在 `docker-compose.yml` 的 `environment` 中引用：

```yaml
environment:
  - CANOPY_API_KEY=${CANOPY_API_KEY}
  - CANOPY_API_SECRET=${CANOPY_API_SECRET}
  - CANOPY_EXCHANGE=${CANOPY_EXCHANGE}
  - CANOPY_LOG_LEVEL=${CANOPY_LOG_LEVEL}
```

## 进入容器调试

```bash
docker compose exec canopy bash
```

## 常见问题

### Docker daemon 未运行

```bash
# macOS — 启动 Docker Desktop 应用
open -a Docker

# 或通过 launchctl
sudo launchctl load /Library/LaunchDaemons/com.docker.vmnetd.plist
```

### 端口冲突

修改 `docker-compose.yml` 添加端口映射：

```yaml
ports:
  - "8080:8000"   # 将宿主机 8080 映射到容器 8000
```

### 镜像重建

```bash
docker compose build --no-cache
docker compose up -d --force-recreate
```
*（内容由AI生成，仅供参考）*
