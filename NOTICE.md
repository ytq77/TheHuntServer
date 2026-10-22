# 来源、修改与第三方许可

TheHuntServer 的 WPF 管理窗口、开服工具、构建脚本和中文文档由 iytq 维护，按 GPL-2.0-or-later 提供。保留并尊重上游各文件原有版权和许可。

- shadNet：Wozzardman/shadnet-p2p，GPL-2.0-or-later。本项目修改 STUN 封装兼容，并启用上游账号示例工具的构建目标。
- BBSC：CLSAMG22/BBSC。游戏服务包含 NoDreamForHunter 来源，原 LICENSE、NOTICE、CREDITS、SUPPORTERS、LICENSE.NoDreamForHunter 在准备和打包时完整保留。增加独立召唤 WebAPI 参数；Windows 另修复本机登录 URL 与实际监听地址不符的问题。
- Protobuf、Abseil：固定源码归档及各自 LICENSE 随源码包保留，准确版本见 recipe/sources.json。
- Windows 二进制动态链接 Qt，携带 MSYS2 提供的 Python、LLVM 和其他运行库。打包时保留工具链 share/licenses 下的许可证，以及完整 pacman 包版本表。Qt 适用 LGPL/GPL 与相关第三方许可；动态库保持独立文件，可替换兼容构建。
- Qt 及 MSYS2 运行库的对应源码、打包脚本与修改可按 runtime-packages.txt 所列版本，从 https://packages.msys2.org/ 与 https://github.com/msys2/MINGW-packages 获取；Qt 官方源码：https://download.qt.io/archive/qt/ 。构建依赖未锁定二进制快照，必须核对发布包内版本表。

Windows 窗口使用系统 .NET Framework/WPF，不另行分发 .NET。账号注册辅助程序复用已固定的上游客户端代码，增加标准输入 JSON 包装；不改变网络协议。铃铛图标为 iytq 在 TheHuntLauncher 项目中绘制的原创标识，生成源码一并保留。

本项目不隶属 Sony、FromSoftware 或原作者，不提供游戏资源，也不替代原项目署名。本项目的 LICENSE 不改变第三方组件的许可。
