# Ubuntu + Docker + Tailscale 部署教程

适用于一组互相信任的玩家部署自己的 BBSC 服务。先读[组件与端口说明](components.md)。此配方依据已使用过的源码和配置整理；**全新主机的完整构建与双人联机复验仍待完成**，不能把文档生成或容器健康视为已完成实机验收。

现有私服不需要执行下面步骤。不要在已部署目录中覆盖配置，也不要让新环境抢占现有端口。

## 1. 准备主机与网络

参考环境是 Ubuntu 22.04 x86_64 云服务器；编译所需较新的 Qt 放在容器中，不需要为此升级宿主系统。

主机需要：

- Docker Engine 与 Compose v2，安装方法见 [Docker 的 Ubuntu 官方教程](https://docs.docker.com/engine/install/ubuntu/)。
- Python 3、Git，以及构建时访问 GitHub、镜像仓库和 Ubuntu 软件源的能力。
- 已登录目标 tailnet 的 Tailscale，玩家可访问这台服务器的 Tailscale IPv4。
- 足够的构建磁盘与内存。shadNet 编译使用两个任务；运行期资源限制不代表编译也只需要同样的内存。

已有 Docker 或 Tailscale 时先检查现状，不重复安装或重置：

```bash
uname -m
docker --version
sudo docker compose version
python3 --version
tailscale status
tailscale ip -4
sudo ss -lntup
```

记录这台服务器的 Tailscale IPv4。后文全部地址都使用它；不要填写某个玩家的局域网 IP、另一台机器的 Tailscale IP 或 `0.0.0.0`。

这套部署只在 Tailscale 地址监听。访问控制需允许目标玩家访问端口表中的服务；如启用了主机防火墙，按当前规则补齐 `tailscale0` 上需要的 TCP/UDP 流量并保留管理入口。无需为了这些服务向公网开放 31313–31315 或 31413–31415。

容器使用 Linux host 网络，共享宿主网络命名空间，实际监听范围由服务的绑定地址决定；不配置 Docker `ports:` 转发。细节见 [Docker host 网络说明](https://docs.docker.com/engine/network/drivers/host/)。

## 2. 取得公开配方

先克隆仓库，再将配方复制到一个**新的独立部署目录**。这样账号、状态和缓存不会写进 Git 工作区：

```bash
git clone https://github.com/ytq77/TheHuntServer.git &&
test ! -e "$HOME/the-hunt-server" &&
cp -a TheHuntServer/recipe "$HOME/the-hunt-server" &&
cd "$HOME/the-hunt-server"
```

任一步失败就停止，确认原因后再继续。如果目标目录已存在，先确认它是旧部署还是尚未完成的准备目录，不合并或覆盖。保存这次教程所在仓库的 commit，便于以后核对配方版本。

## 3. 下载源码并生成首次配置

在新部署目录执行：

```bash
server_ip="$(tailscale ip -4)"
python3 prepare.py --server-ip "$server_ip"
```

准备程序使用配方中固定的源码版本和 SHA256，生成构建材料，并为首次部署创建配置与注册密钥。它不启动容器、不创建玩家账号，也不修改防火墙。已有不一致的配置应先核对，不能直接用新模板盖掉。

主要材料：

| 路径 | 用途 |
|---|---|
| `.build/vendor-source/` | shadNet、Protobuf、Abseil 的固定源码归档 |
| `.build/game-app/` | BBSC 游戏服务源文件、端口隔离补丁及许可证 |
| `.env` | 本次部署的地址与镜像配置 |
| `shadnet-state/shadnet.cfg` | 实际服务设置和私有注册密钥 |
| `game-state/` | BBSC 在线数据和日志 |

下载失败或校验不符时先停止。不要删掉校验逻辑、随意使用 `main` 最新代码或混入其他镜像版本。如果云服务器不能访问下载源，可以在能联网的机器取得同一配方的已校验缓存，再复制到服务器，用 `prepare.py --server-ip "$server_ip" --offline` 复核并准备；离线模式并不提供 Docker 基础镜像和 apt 软件包。

`.env.example`、`shadnet.cfg.example` 是公开模板；生成的 `.env`、实际 cfg、状态目录和数据库应留在管理员机器上。

## 4. 构建和启动

容器内使用 UID/GID 10001。确认当前目录正确、状态目录是刚创建的这套环境后，调整其所有者：

```bash
pwd
sudo chown -R 10001:10001 shadnet-state game-state
sudo docker compose config --quiet
sudo docker compose build
sudo docker compose up -d
sudo docker compose ps
```

配方中的 Dockerfile 从公开基础镜像与固定源码构建，不依赖此前私服机器上的 `local/...` 旧镜像。这里产生的镜像标签仍是你这台机器的本地标签，不会自动上传到公共镜像仓库。

启动后检查：

```bash
sudo docker compose logs --since 5m --tail 100 shadnet gameserver
sudo ss -lntup | grep -E ':(31413|31414|31415|20443|20444)\b'
```

应有 shadNet 的 TCP 31413、UDP 31414、TCP 31415，以及游戏服务 TCP 20443 和 Relay TCP 20444，绑定到所填服务器地址。

本模式显式禁用 bbhost，不需要为了它额外开放 18671 或 3478。BBSC 的 `20444` Relay 在此固定版本中是广播式转发，**只适合一组可信玩家共同测试，不提供多组独立房间之间的隔离**。不要把它当成面向陌生人的公共联机平台。

## 5. 检查游戏服务的路由

从能访问服务器的 Linux 终端执行：

```bash
curl --fail --max-time 5 "http://$server_ip:31415/status"
curl --fail --max-time 5 "http://$server_ip:20443/bb-eu/ss.info" \
  | base64 --decode
```

第二项解码得到 XML 片段。四个 `api_SummonData*` 应指向本服务器的 `http://地址:31415`；本地游戏在线接口指向 `http://地址:20443`。这一步能发现“容器正常，但实际召唤被导向普通联机 31315”的配置混用。

若在另一终端运行，先重新设置 `server_ip`。HTTP 可达只说明对应接口回应，UDP/STUN 和游戏联机还需后续验证。

## 6. 创建玩家账号

服务正常启动后，在部署目录执行：

```bash
sudo python3 create-account.py
```

工具交互询问用户名、邮箱和密码，使用本套配置中的注册密钥调用服务自身的注册/登录功能。为第二名玩家再运行一次。它不会把玩家密码写进命令行示例或公开模板。

工具内部调用上游 `shadnet-sample`，凭据会短暂存在于管理员主机的进程参数中。请在受信任的管理员主机上运行，不把进程命令行或调试输出发到公开问题单。

- 使用不同的用户名；本配方使用 3–16 位 ASCII 字母、数字、下划线或连字符，以适应客户端端点字段。
- 每个账号使用独立邮箱标识，并满足工具显示的格式约束。
- 同时游玩的玩家不要共用一个账号。
- 账号属于本套 shadNet 数据库；在公共服务器、普通联机环境或 Discord 上已有账号，不代表这里已创建。

账号工具的验证只覆盖注册与登录，不代表召唤成功。改名、删号或重建数据库应先备份；不要直接照抄 SQL 修改正在使用的数据库。

## 7. 配置两台玩家电脑

The Hunt 的「游戏与联机」填写：

| 字段 | 填法 |
|---|---|
| shadNet 合作服务器 | `服务器TailscaleIPv4:31413` |
| shadNet WebAPI | `http://服务器TailscaleIPv4:31415` |
| BBSC 游戏服务 | `http://服务器TailscaleIPv4:20443` |
| BBSC Relay | `服务器TailscaleIPv4:20444` |
| 账号 / 密码 | 第 6 步在本套服务创建的个人账号 |

两人填相同四个服务地址、不同账号，并使用同一兼容版本的客户端。画质配置和游戏文件仍选择各自电脑上的路径。Tailscale 环境不依赖 UPnP。

客户端通过路由器的 Tailscale 子网路由接入时，参考[子网路由排错](troubleshooting.md#5-一台电脑通过路由器的-tailscale-子网路由)；不能仅凭能打开 WebAPI 就认定对端数据路径也正常。

## 8. 双人验收

1. 两人进入在线并读档，确认五件 BBSC 猎具分类、名称和图标正常。
2. 一人使用唤猎之铃，另一人使用应猎之铃；先在便于观察的相近位置测试。
3. 确认进入同一世界，互相能看到移动、攻击和伤害。
4. 分别让房主、客机死亡，观察是否保持联机并在提灯复活。
5. 检查同行传送，以及 Boss 战结束后的会话保持。
6. 正常退出，再重新启动并登录，确认状态持久化。

把成功和失败项目分别记录，附时间和两个客户端版本。遇到问题按[排错说明](troubleshooting.md)逐层检查；不要用“容器 healthy”替代这些结果。

## 9. 后续维护

首次成功后保存一致性备份和构建版本，按[维护与回滚说明](operations.md)操作。普通启动器更新不要求立即升级服务器；客户端核心和服务端应分别根据兼容性验证决定版本。
