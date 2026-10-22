# 配方来源与验证边界

这是给新 Linux 主机准备的构建配方，不是正在运行的服务器的配置备份。
请先阅读上一级服务端教程；不要用此目录覆盖现有部署。

- shadNet：`Wozzardman/shadnet-p2p`，固定提交
  `5a849a192fd4450593c57b10697316ac324c856e`，GPL-2.0-or-later。
- Protobuf、Abseil 及 BBSC 的准确提交和源文件 SHA256 记录在
  [`sources.json`](sources.json)。准备程序先校验再使用。
- `fixes/stun_server.cpp` / `.h` 保留原版权和许可证声明，只修正四字节旧封装、
  六字节 PS4 封装的识别及对应回复；不修改匹配规则和数据库结构。
- BBSC 游戏服务取自 `CLSAMG22/BBSC` 的
  `315f76c38b1ca5843b082f93f47927a9193ad94a`。源码调整包括添加
  `--shadnet-webapi`，使召唤地址可以使用独立的 `31415` 端口，并使本机登录 URL 使用实际监听地址。
  BBSC 的 LICENSE、NOTICE、CREDITS、SUPPORTERS 和
  `LICENSE.NoDreamForHunter` 一起下载到 `.build/game-app`。
- shadNet 镜像保留校验后的完整源归档、源版本表及 STUN 补丁，位于镜像内
  `/usr/local/share/shadnet/`。系统 Qt 依赖由 Ubuntu 包管理器提供。

当前验证：本地固定源材料的离线准备、重复运行保留配置、拒绝冲突配置、
STUN 补丁与已测试版本一致、BBSC 服务与已测试的隔离端口版本一致、
四个召唤 URL 均指向 `31415`，以及 Compose 和 Shell 语法检查。
**这份独立 Dockerfile 尚未完成干净 Linux 环境的完整构建和双人运行复验。**
Ubuntu 基础镜像使用固定日期标签，APT 软件包未锁定快照版本，因此这不保证
每次构建的二进制逐字节一致。

`prepare.py` 支持 `--offline`，要求 `.build/vendor-source` 中的三份归档，
以及 `.build/bbsc-original` 中的 BBSC 原始文件已缓存且摘要正确。
它不启动容器，不创建玩家账号，也不更改防火墙。
生成后的配置和数据属于本机私人状态；不要提交或上传。
Linux 上把状态目录所有权交给 UID/GID 10001 后，再次准备或管理账号通常需要
`sudo` 才能读取权限为 `600` 的配置。

`create-account.py` 只用于注册新账号，随后进行一次登录验证；请在该账号没有
运行游戏时使用。用户名使用 3–16 位 ASCII 字母、数字、下划线或连字符，
每个账号需要不同的邮件地址字段。此配方关闭邮件验证，不发送邮件。
密码交互输入，不写入 Shell 历史或工具输出。由于上游 `shadnet-sample`
以命令行参数接收密码和注册密钥，服务器本机管理员仍可短暂看到其进程参数。

此配方的 `20444/TCP` Relay 会向所有接入者广播模组消息，未按房间隔离，
因此只适合一组互相信任的玩家。`--no-bbhost` 已关闭另一套 bbhost 服务；
此配方不需要开放 `18671`、`3478` 或账号网站端口 `31316`。
