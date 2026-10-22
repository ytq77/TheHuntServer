# 构建与发布

固定源码版本和 SHA256 位于 `recipe/sources.json`。构建时下载并校验，已有缓存也须重新核对；不自动追踪上游 main。

## Windows 本机构建

安装 MSYS2 CLANG64，安装以下包及其依赖：

```bash
pacman -S --needed mingw-w64-clang-x86_64-toolchain \
  mingw-w64-clang-x86_64-cmake mingw-w64-clang-x86_64-ninja \
  mingw-w64-clang-x86_64-python mingw-w64-clang-x86_64-qt6-base \
  mingw-w64-clang-x86_64-qt6-websockets mingw-w64-clang-x86_64-qt6-httpserver
```

在仓库根目录的 PowerShell 中执行，替换实际 CLANG64 路径：

```powershell
.\windows\build-native.ps1 -Toolchain C:\msys64\clang64
```

脚本依次准备固定源码、编译服务与账号工具、运行上游 CTest、打包运行库、验证中文空格路径下的运行、两个独立数据库、账号持久性、STUN 两种格式、召唤流程、双向 Relay、本机登录地址，最后输出 `windows/dist/TheHuntServer-Windows-v版本.zip`。

在同一工具链环境执行 `python scripts/archive-source.py`，生成根目录 `dist` 下的 Windows ZIP、完整固定源码 ZIP、Linux 配方 ZIP 和 SHA256SUMS.txt。源码包只读取 Git 已登记文件和固定清单中的已校验下载，排除账号、私钥、日志和测试状态。

源码包解压后再次构建，Windows 会复用 `windows/downloads`；Linux 可将同一缓存复制到配方 `.build` 的对应位置，参见部署教程。操作系统依赖仍需安装。

MSYS2 编译器、Qt、Python 由包管理器提供；版本记录在 BUILD-INFO.json 和 licenses/runtime-packages.txt。当前不承诺不同时点的二进制逐字节一致。

## GitHub Actions

- push main、PR、手动运行：构建并测试 Windows 原生包；在全新 Linux runner 构建云端镜像并检查 HTTP 路由和 STUN。
- Linux 测试使用 runner 临时回环接口上的示例地址，离线模拟 Tailscale 地址空间，不接入私人 tailnet。
- Windows 产物包含完整源码包、Linux 配方和校验表；Actions 产物保留 14 天。
- 推送与 VERSION 一致的 `v版本` 标签，待两端构建通过后自动发布 Release。含连字符的版本标记为预发布。
- 自动构建不部署到私人服务器，不更改现有账号和客户端。

发布前更新 VERSION 和 `docs/releases/v版本.md`，提交、推送并确认主分支通过，再推送标签。测试版本不会自动变成稳定版本。
