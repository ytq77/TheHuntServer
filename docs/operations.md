# 维护、备份与升级

以下命令都在你部署这套 BBSC 服务的 **Compose 目录**执行。先用 `pwd` 和 `sudo docker compose ps` 确认对象；不要在另一个项目目录操作。普通联机与 BBSC 使用不同状态目录，分别备份。

## 日常检查

```bash
pwd
sudo docker compose ps
sudo docker compose logs --since 10m --tail 100 shadnet gameserver
sudo docker compose images
```

保留镜像标签、镜像 ID、构建源码版本及最近一次双人测试结果。`healthy` 只证明配置的健康探针通过，不代表双人联机成功。

按需启停本项目：

```bash
sudo docker compose stop shadnet gameserver
sudo docker compose start shadnet gameserver
```

停止不会删除绑定挂载的状态目录。服务器上有其他 Docker 服务时，不要使用全局清理或批量停止命令。

## 哪些数据需要保留

| 内容 | 用途 |
|---|---|
| `.env`、Compose、实际 `shadnet.cfg` | 地址、镜像选择、监听与注册配置 |
| `shadnet-state/` | shadNet 配置及账号等持久数据 |
| `game-state/` | BBSC 在线数据、公告及日志 |
| 源码版本 / 补丁 / 镜像 ID | 重新构建或回滚程序所需依据 |

游戏角色存档在**玩家电脑**的普通版或 The Hunt 独立存档目录中，不由云服务器备份代替。账号数据库与游戏角色存档是不同的数据。

状态目录和备份属于管理员的私人资料，不提交到 GitHub。只分享教程中的示例文件。

## 一致性备份

最简单的方式是双方先退出游戏，再短暂停止这套服务，备份两个完整状态目录。不要在数据库或 JSON 文件持续写入时直接复制并称为一致性备份。

在确认的 Compose 目录执行：

```bash
set -eu
umask 077
backup_dir="$(pwd)/backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
sudo docker compose config --images > "$backup_dir/images.txt"
sudo docker compose images > "$backup_dir/image-details.txt"
sudo docker compose stop shadnet gameserver

# 无论备份成功与否，都尝试恢复本项目服务；失败时仍应查看状态和日志。
trap 'sudo docker compose start shadnet gameserver' EXIT
sudo tar -czf "$backup_dir/state.tar.gz" \
  .env compose.yaml shadnet-state game-state
sudo tar -tzf "$backup_dir/state.tar.gz" > /dev/null
sudo sha256sum "$backup_dir/state.tar.gz" > "$backup_dir/SHA256SUMS.txt"
sudo docker compose start shadnet gameserver
trap - EXIT
sudo docker compose ps
```

首次使用前确保两个状态目录已经初始化。备份成功后，另外保存当前所使用的源码版本、补丁和镜像；必要时可用 `docker image save` 导出指定镜像供离线回滚。保留一份服务器之外的备份，并实际演练恢复。

## 程序升级

1. 阅读变更，确认要升级的是 shadNet、BBSC 游戏服务，还是客户端核心。
2. 在单独目录准备新源码与配置，不覆盖现有状态目录。
3. 优先使用独立测试主机。同机测试时，除独立目录和未占用端口外，还必须将测试 Compose 的顶层 `name:` 改为独立项目名（如 `the-hunt-bbsc-test`），以免操作选中生产容器；模板默认的 `the-hunt-bbsc` 不能在同机两套环境中共用。同步修改服务监听、健康探针和 `ss.info` 的地址，避免请求误入生产服务。准备工具只针对默认基线，定制测试配置后不要重新运行它覆盖或校验生产配置。
4. 完成构建、启动、账号认证、UDP/STUN 和双人实测。
5. 约好玩家退出，做一致性备份，保留旧镜像。
6. 将生产 Compose 的镜像改成已验证的具体版本，只重建需要升级的服务。

例如只更换 shadNet 镜像：

```bash
sudo docker compose up -d --no-deps --no-build shadnet
sudo docker compose ps
sudo docker compose logs --since 5m --tail 100 shadnet
```

仅在镜像已经存在且配置已核对时执行。游戏服务升级也按同样方式定向更新 `gameserver`。新版本是否需要数据迁移，必须根据该版本说明判断。

## 回滚

程序故障且数据格式没有变化时，优先恢复之前的镜像引用和配置，再定向重建该容器。**不要因为换回旧程序就把账号数据库一并恢复成旧备份**，否则会丢失备份之后的数据。

只有数据损坏或明确需要回退数据迁移时，才恢复状态备份：

1. 所有玩家退出；停止本套服务。
2. 先备份当前故障状态，保留诊断和恢复机会。
3. 将备份解压到新的恢复目录，检查归档路径、内容、文件所有者和校验值。
4. 明确将哪些目录切换为恢复副本，确认没有混入普通联机环境。
5. 启动并检查账号认证和双人联机。

数据恢复不提供一条覆盖现有目录的通用命令，以免把不同部署或不同时点的状态混在一起。

## 普通启动器升级后

The Hunt 固定自己的 BBport/BBSC 版本。普通版升级不会自动替换包内核心，但 The Hunt 仍会同步普通版画质设置并引用部分补丁配置，需检查格式与行为是否兼容。

想让 The Hunt 获得新核心修复时，先适配并验证客户端，再发布新包。服务端按协议变化或具体修复需要升级；无需因为普通启动器出了一个新版本就重建镜像。当前仓库没有自动跟随上游或自动更新私人服务器的任务。
