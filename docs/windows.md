# The Hunt · Windows 原生私服测试版

这是独立仓库的 Windows 原生预览包，无需 Docker，无需另装 Qt 或 Python。目标系统为 Windows 10/11 x64。

双击 `Server.cmd`，选择普通联机或 BBSC 无缝联机。窗口需要保持打开，按 Ctrl+C 停止本次服务。
服务会在服务启动就绪后，按客户端字段逐项打印实际 IP、端口和完整 HTTP 地址，方便直接复制。无缝模式显示四项地址，普通模式显示合作服务器和 WebAPI；同时显示创建账号入口。本机回环地址会明确提示仅限本机连接。
本版修正开服电脑自己登录失败：只监听局域网或 Tailscale 地址时，返回给本机游戏的登录地址也使用该监听地址，避免被错误改成未监听的 127.0.0.1。开服电脑仍填写窗口中显示的同一组地址。
默认只监听 `127.0.0.1`，不会对其他电脑开放，也不会修改 Windows 防火墙或现有云服务器。

要进行双机测试，先选择“配置监听地址”，填服务器这台电脑的实际局域网或 VPN IPv4，再启动。
可以使用局域网、Tailscale 或其他能提供双向 IPv4 通信的虚拟局域网；两台客户端都填写这台服务器的可达地址。
两台客户端均须可达开服地址；在主机防火墙按下表放行所用模式的 TCP/UDP 端口。

| 用途 | 普通联机 | BBSC 无缝联机 |
|---|---|---|
| 合作服务器 TCP | IP:31313 | IP:31413 |
| STUN UDP | 31314 | 31414 |
| WebAPI HTTP | http://IP:31315 | http://IP:31415 |
| BBSC 游戏服务 HTTP | 不含普通版游戏服务 | http://IP:20443 |
| BBSC Relay TCP | 不需要 | IP:20444 |

普通版的留言、血迹等游戏服务可继续使用原有地址；这个包的普通模式提供 shadNet 合作服务。
如普通版客户端仍有旧服务器的 host_overrides 自定义规则，需要在下一轮测试时一起核对，单改合作服务器字段可能不足。

在另一个窗口打开 `Server.cmd`，选择创建对应模式的账号。必须先启动该模式的服务器。
两个模式的账号和数据库互相独立。没有预置个人账号、密码或私有服务器地址。
密码不会回显或写入启动脚本；上游账号工具通过进程参数接收密码，本机管理员能够查看这些参数。

目录说明：

- `normal/db`：普通联机数据库；`bbsc/db`：无缝联机数据库。
- `normal/logs`、`bbsc/logs`：各自运行日志。
- 各模式的 `shadnet.cfg`：首次启动生成，含随机注册密钥，请妥善保管。
- `bbsc/online-data.json`：无缝游戏服务数据。
- `runtime`：共用 Qt、Python 运行库；`bbsc-game`：游戏服务与 Relay 源码。
- `source-manifest.json`、`BUILD-INFO.json`、`licenses`：固定源码版本、构建信息与许可文件。

测试版范围：保留已验证过的 4/6 字节 STUN 兼容修复；BBSC 使用独立 WebAPI 端口。
BBSC Relay 是单组玩家共享广播，未提供房间隔离；适用于互相信任的一组玩家，不要直接作为公开多人平台使用。
当前包未实现图形管理界面、Windows 服务安装或自动防火墙配置。
备份时先停止服务，再复制 `normal`、`bbsc` 和 `server.json`。

构建来源与修改：shadNet 固定版本和 BBSC 固定版本见 `source-manifest.json`。
shadNet 仅加现有 STUN 兼容修复、启用账号工具的构建目标；BBSC 增加显式 `--shadnet-webapi` 参数，并修正本机登录地址与实际监听地址不一致的问题。
原作者与第三方许可保留在 `licenses`，BBSC 原始署名同时保留在 `bbsc-game`。
完整源码包和 Linux 配方与二进制一起提供，详见 https://github.com/ytq77/TheHuntServer 。

## 更新已有 Windows 服务

先让玩家退出，并用 Ctrl+C 停止服务，备份旧目录。将新版本解压到新的目录，再从旧目录复制持久数据：

- 根目录 `server.json`：已选监听地址。不要用新包的回环默认值覆盖它。
- `normal/shadnet.cfg`、`normal/db/`：普通模式配置与账号。
- `bbsc/shadnet.cfg`、`bbsc/db/`、`bbsc/online-data.json`：无缝模式配置、账号与在线数据。
- 如自行修改过各模式的 `worlds.cfg`、`scoreboards.cfg`，一并保留；日志可另外归档。

只复制旧目录中实际存在的上述数据，不复制旧版 exe、runtime 或 bbsc-game。新目录保留新程序和运行库，旧目录留作回滚；不要让两份服务同时占用同一组端口。启动后核对打印地址和已有账号登录，再让两人进入游戏。

服务端账号不是角色存档。迁移服务端不需要把玩家的游戏存档上传到开服电脑。
