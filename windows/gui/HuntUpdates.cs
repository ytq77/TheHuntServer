// SPDX-License-Identifier: GPL-2.0-or-later
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

public sealed class HuntRelease
{
    public string Version, Notes, Page, Download, Sha256;
    public long Size;
    public bool VerifiedOrigin;
}

public static class HuntUpdates
{
    [DllImport("dwmapi.dll")] private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);
    private static readonly Regex VersionPattern = new Regex(@"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*))?$");

    public static int CompareVersions(string left, string right) {
        var a = VersionPattern.Match(left); var b = VersionPattern.Match(right);
        if (!a.Success || !b.Success) throw new ArgumentException("无法识别版本号。");
        for (int i = 1; i <= 3; ++i) {
            int order = Int64.Parse(a.Groups[i].Value).CompareTo(Int64.Parse(b.Groups[i].Value));
            if (order != 0) return order;
        }
        string first = a.Groups[4].Value, second = b.Groups[4].Value;
        if (first == second) return 0;
        if (first.Length == 0) return 1;
        if (second.Length == 0) return -1;
        var x = first.Split('.'); var y = second.Split('.');
        for (int i = 0; i < Math.Min(x.Length, y.Length); ++i) {
            long nx, ny; bool ax = Int64.TryParse(x[i], out nx), by = Int64.TryParse(y[i], out ny);
            int order = ax && by ? nx.CompareTo(ny) : ax != by ? (ax ? -1 : 1) : String.CompareOrdinal(x[i], y[i]);
            if (order != 0) return order;
        }
        return x.Length.CompareTo(y.Length);
    }

    public static string ValidatePrefix(string prefix) {
        prefix = (prefix ?? "").Trim();
        if (prefix.Length == 0) return "";
        Uri uri;
        if (!Uri.TryCreate(prefix, UriKind.Absolute, out uri) || uri.Scheme != "https" ||
            uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0)
            throw new ArgumentException("GitHub 加速前缀必须是 HTTPS 地址，且不含账号、查询参数或锚点。");
        return uri.AbsoluteUri.TrimEnd('/') + "/";
    }

    private static string AssetName(string repository, string version) {
        if (repository == "TheHuntLauncher") return "BBSC-Launcher-" + version + "-windows-x64.zip";
        if (repository == "TheHuntServer") return "TheHuntServer-Windows-v" + version + ".zip";
        throw new ArgumentException("未知的更新项目。");
    }

    public static HuntRelease SelectRelease(string data, string repository, bool previews) {
        AssetName(repository, "0.0.0");
        var serializer = new JavaScriptSerializer { MaxJsonLength = 2097152 };
        object[] releases;
        try { releases = serializer.DeserializeObject(data) as object[]; }
        catch (ArgumentException) { throw new InvalidDataException("版本接口未返回有效 JSON；加速服务可能只支持下载，不支持 GitHub API。"); }
        if (releases == null) throw new InvalidDataException("版本接口未返回有效列表；加速服务可能不支持 GitHub API。");
        HuntRelease best = null;
        foreach (var item in releases) {
            var release = item as Dictionary<string, object>;
            if (release == null || !release.ContainsKey("tag_name") ||
                !release.ContainsKey("draft") || !release.ContainsKey("prerelease") ||
                Convert.ToBoolean(release["draft"]) || (!previews && Convert.ToBoolean(release["prerelease"]))) continue;
            string tag = Convert.ToString(release["tag_name"]);
            if (!VersionPattern.IsMatch(tag)) continue;
            string version = tag.TrimStart('v');
            if (!previews && version.Contains("-")) continue;
            if (!release.ContainsKey("assets")) continue;
            var assets = release["assets"] as object[];
            if (assets == null) continue;
            string name = AssetName(repository, version);
            string path = "https://github.com/ytq77/" + repository + "/releases/";
            string download = path + "download/" + Uri.EscapeDataString(tag) + "/" + name;
            foreach (var value in assets) {
                var asset = value as Dictionary<string, object>;
                if (asset == null || !asset.ContainsKey("name") || !asset.ContainsKey("browser_download_url") ||
                    !asset.ContainsKey("state") || Convert.ToString(asset["name"]) != name ||
                    Convert.ToString(asset["state"]) != "uploaded" || Convert.ToString(asset["browser_download_url"]) != download) continue;
                if (best == null || CompareVersions(version, best.Version) > 0)
                    best = new HuntRelease { Version = version, Download = download,
                        Page = path + "tag/" + Uri.EscapeDataString(tag),
                        Notes = release.ContainsKey("body") ? Convert.ToString(release["body"]) : "暂无更新说明。",
                        Sha256 = asset.ContainsKey("digest") && Regex.IsMatch(Convert.ToString(asset["digest"]), @"^sha256:[a-f0-9]{64}$") ? Convert.ToString(asset["digest"]).Substring(7) : "",
                        Size = asset.ContainsKey("size") ? Convert.ToInt64(asset["size"]) : 0 };
            }
        }
        if (best == null) throw new InvalidDataException("尚无符合此频道且包含完整 Windows 包的发布版本。");
        return best;
    }

    private static HttpWebRequest Request(string url, string proxy) {
        ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
        var request = (HttpWebRequest)WebRequest.Create(url);
        request.Timeout = 10000; request.ReadWriteTimeout = 30000;
        request.UserAgent = "TheHunt-UpdateCheck";
        request.Accept = "application/vnd.github+json";
        request.Proxy = null;
        if (!String.IsNullOrWhiteSpace(proxy)) {
            Uri address;
            if (!Uri.TryCreate(proxy.Trim(), UriKind.Absolute, out address) ||
                (address.Scheme != "http" && address.Scheme != "https") || address.UserInfo.Length != 0 ||
                address.Query.Length != 0 || address.Fragment.Length != 0 || address.AbsolutePath != "/")
                throw new ArgumentException("HTTP 代理请填写 http(s)://地址:端口，不包含账号密码或路径。");
            request.Proxy = new WebProxy(address);
        }
        return request;
    }

    private static string Fetch(string url, string proxy) {
        var request = Request(url, proxy);
        using (var response = request.GetResponse())
        using (var stream = response.GetResponseStream())
        using (var memory = new MemoryStream()) {
            var buffer = new byte[8192]; int count;
            while ((count = stream.Read(buffer, 0, buffer.Length)) > 0) {
                if (memory.Length + count > 2097152) throw new InvalidDataException("版本响应过大，已停止读取。");
                memory.Write(buffer, 0, count);
            }
            return Encoding.UTF8.GetString(memory.ToArray());
        }
    }

    public static HuntRelease Check(string repository, bool previews, string proxy, string prefix) {
        AssetName(repository, "0.0.0"); prefix = ValidatePrefix(prefix);
        string url = "https://api.github.com/repos/ytq77/" + repository + "/releases?per_page=100";
        try { var release = SelectRelease(Fetch(url, proxy), repository, previews); release.VerifiedOrigin = true; return release; }
        catch (WebException) {
            if (prefix.Length == 0) throw new IOException("无法连接 GitHub，或请求受到限流。可配置 HTTP 代理或 GitHub 加速前缀后重试。");
        }
        // Some download accelerators also support GitHub API requests. Never send login credentials.
        try { return SelectRelease(Fetch(prefix + url, proxy), repository, previews); }
        catch (WebException) { throw new IOException("直连和加速查询均失败。此加速地址可能只支持下载；可尝试本机 HTTP 代理。"); }
    }

    public static void WatchStartup(Window owner, Button button, string root, string repository, string version) {
        AssetName(repository, version);
        WatchStartupCore(owner, button, version, () => {
            var saved = new Dictionary<string, object>();
            string path = Path.Combine(root, "update-settings.json");
            if (File.Exists(path))
                saved = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
            bool previews = saved.ContainsKey("previews") ? Convert.ToBoolean(saved["previews"]) : version.Contains("-");
            string proxy = saved.ContainsKey("http_proxy") ? Convert.ToString(saved["http_proxy"]) : "";
            string prefix = saved.ContainsKey("download_prefix") ? Convert.ToString(saved["download_prefix"]) : "";
            return Check(repository, previews, proxy, prefix);
        });
    }

    internal static void WatchStartupCore(Window owner, Button button, string version, Func<HuntRelease> query) {
        EventHandler rendered = null;
        rendered = async delegate {
            owner.ContentRendered -= rendered; // A window may render again after hide/show.
            try {
                var release = await Task.Run(query);
                if (!owner.IsVisible) return;
                if (CompareVersions(release.Version, version) > 0) {
                    button.Content = "发现新版";
                    button.BorderBrush = Color("#B9C5CD");
                    button.ToolTip = "发现新版本 " + release.Version + "，点击查看说明并选择是否更新。";
                } else button.ToolTip = "启动检查完成，当前频道暂无更新。";
            } catch {
                if (owner.IsVisible) button.ToolTip = "启动时未能检查更新，可点击手动重试或设置更新网络。";
            }
        };
        owner.ContentRendered += rendered;
    }

    public static void EnsureNotUpdating(string root) {
        string path = Path.Combine(root, ".update.lock");
        if (!File.Exists(path)) return;
        try { using (File.Open(path, FileMode.Open, FileAccess.Read, FileShare.None)) { } }
        catch (IOException) { throw new IOException("此目录正在更新，请等待更新窗口完成后再启动。"); }
    }

    private static string PrepareUpdate(HuntRelease release, string root, string repository, string proxy, string prefix, IProgress<int> progress, CancellationToken cancellation) {
        if (!release.VerifiedOrigin || release.Sha256.Length != 64 || release.Size <= 0 || release.Size > 2147483648L)
            throw new InvalidDataException("自动更新需要从 GitHub 核对 SHA256。请用直连或本机 HTTP 代理重新检查。");
        string helper = Path.Combine(root, "Apply-Update.ps1");
        if (!File.Exists(helper)) throw new IOException("缺少自动更新助手，请先安装完整发行包。");
        string session = Path.Combine(Path.GetTempPath(), "TheHuntUpdates", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(session);
        string archive = Path.Combine(session, "update.zip");
        var request = Request(ValidatePrefix(prefix) + release.Download, proxy);
        request.Accept = "application/octet-stream";
        using (var abort = cancellation.Register(request.Abort))
        using (var response = request.GetResponse())
        using (var stream = response.GetResponseStream())
        using (var file = File.Create(archive))
        using (var hash = SHA256.Create()) {
            var buffer = new byte[65536]; int count; long size = 0;
            while ((count = stream.Read(buffer, 0, buffer.Length)) > 0) {
                cancellation.ThrowIfCancellationRequested();
                size += count;
                if (size > release.Size) throw new InvalidDataException("下载内容超过预期大小，已停止更新。");
                hash.TransformBlock(buffer, 0, count, null, 0); file.Write(buffer, 0, count);
                progress.Report((int)(100 * size / release.Size));
            }
            hash.TransformFinalBlock(new byte[0], 0, 0);
            if (size != release.Size || BitConverter.ToString(hash.Hash).Replace("-", "").ToLowerInvariant() != release.Sha256)
                throw new InvalidDataException("更新包 SHA256 校验失败，未安装。请更换下载线路后重试。");
        }
        cancellation.ThrowIfCancellationRequested();
        File.Copy(helper, Path.Combine(session, "Apply-Update.ps1"));
        File.WriteAllText(Path.Combine(session, "plan.json"), new JavaScriptSerializer().Serialize(new {
            root = Path.GetFullPath(root), repository = repository, version = release.Version,
            parent_pid = Process.GetCurrentProcess().Id, archive = archive, sha256 = release.Sha256
        }), new UTF8Encoding(false));
        return session;
    }

    private static Brush Color(string value) { return new SolidColorBrush((System.Windows.Media.Color)ColorConverter.ConvertFromString(value)); }
    private static TextBlock Text(string value) { return new TextBlock { Text = value, TextWrapping = TextWrapping.Wrap, Foreground = Color("#CFD4D5"), Margin = new Thickness(0, 0, 0, 8) }; }

    public static void Show(Window owner, string root, string repository, string version) {
        Show(owner, root, repository, version, () => false);
    }

    public static void Show(Window owner, string root, string repository, string version, Func<bool> canInstall) {
        AssetName(repository, version);
        var window = new Window { Title = "检查更新 · " + repository, Owner = owner, Width = 650, Height = 690,
            MinWidth = 580, MinHeight = 600, WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Background = Color("#171C20"), Foreground = Color("#DFE3E4"), FontFamily = owner.FontFamily, FontSize = 13 };
        window.Resources.MergedDictionaries.Add(owner.Resources);
        if (owner.Icon != null) window.Icon = owner.Icon;
        window.SourceInitialized += delegate { int dark = 1; DwmSetWindowAttribute(new System.Windows.Interop.WindowInteropHelper(window).Handle, 20, ref dark, 4); };
        var layout = new Grid { Margin = new Thickness(24) };
        layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        layout.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var fields = new StackPanel(); layout.Children.Add(fields);
        fields.Children.Add(new TextBlock { Text = "当前版本  " + version, FontSize = 19, Foreground = Color("#E0DFD5"), Margin = new Thickness(0, 0, 0, 18) });
        var previews = new CheckBox { Content = "接收预览版更新", IsChecked = version.Contains("-"), Foreground = Color("#D2D6D7"), Margin = new Thickness(0, 0, 0, 14) };
        fields.Children.Add(previews);
        fields.Children.Add(Text("HTTP 代理（选填，例如 http://127.0.0.1:7890）"));
        var proxy = new TextBox { Padding = new Thickness(8), Margin = new Thickness(0, 0, 0, 14) }; fields.Children.Add(proxy);
        fields.Children.Add(Text("GitHub 下载加速前缀（选填，例如 https://你的加速站/）"));
        var prefix = new TextBox { Padding = new Thickness(8), Margin = new Thickness(0, 0, 0, 10) }; fields.Children.Add(prefix);
        fields.Children.Add(Text("留空默认直连。查询优先直连，失败后尝试加速；部分加速站仅支持下载。设置只用于更新，不影响游戏联机。"));
        string settings = Path.Combine(root, "update-settings.json");
        try {
            if (File.Exists(settings)) {
                var saved = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(settings));
                if (saved.ContainsKey("http_proxy")) proxy.Text = Convert.ToString(saved["http_proxy"]);
                if (saved.ContainsKey("download_prefix")) prefix.Text = Convert.ToString(saved["download_prefix"]);
                if (saved.ContainsKey("previews")) previews.IsChecked = Convert.ToBoolean(saved["previews"]);
            }
        } catch { fields.Children.Add(Text("上次的更新设置无法读取，请重新填写。")); }
        var status = Text("自动更新会校验、备份并替换程序，保留账号、存档和设置。安装前请退出游戏或停止服务。"); fields.Children.Add(status);
        var notes = new TextBox { IsReadOnly = true, TextWrapping = TextWrapping.Wrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            Background = Color("#111619"), Foreground = Color("#CDD4D8"), BorderBrush = Color("#46525A"), Padding = new Thickness(12), Margin = new Thickness(0, 10, 0, 18) };
        Grid.SetRow(notes, 1); layout.Children.Add(notes);
        var buttons = new WrapPanel(); Grid.SetRow(buttons, 2); layout.Children.Add(buttons);
        var check = new Button { Content = "检查更新", Padding = new Thickness(16, 8, 16, 8), Margin = new Thickness(0, 0, 10, 0) };
        var download = new Button { Content = "手动下载", Padding = check.Padding, Margin = check.Margin, IsEnabled = false };
        var page = new Button { Content = "发布页", Padding = check.Padding };
        var install = new Button { Content = "自动更新", Padding = check.Padding, Margin = check.Margin, IsEnabled = false };
        buttons.Children.Add(check); buttons.Children.Add(install); buttons.Children.Add(download); buttons.Children.Add(page);
        HuntRelease release = null; string downloadPrefix = "";
        page.Click += delegate { Process.Start(new ProcessStartInfo("https://github.com/ytq77/" + repository + "/releases") { UseShellExecute = true }); };
        download.Click += delegate {
            if (release != null) Process.Start(new ProcessStartInfo(downloadPrefix + release.Download) { UseShellExecute = true });
        };
        bool installing = false; CancellationTokenSource cancelDownload = null;
        window.Closing += delegate(object sender, System.ComponentModel.CancelEventArgs args) {
            if (installing && cancelDownload != null) cancelDownload.Cancel();
        };
        install.Click += async delegate {
            if (release == null) return;
            if (!canInstall()) { status.Text = "请先退出游戏、停止两种联机服务，并等待当前操作结束，再安装更新。"; return; }
            installing = true; install.IsEnabled = check.IsEnabled = download.IsEnabled = false;
            cancelDownload = new CancellationTokenSource();
            try {
                string proxyValue = proxy.Text.Trim();
                var progress = new Progress<int>(value => { if (window.IsVisible) status.Text = "正在下载并校验更新包…… " + value + "%"; });
                string session = await Task.Run(() => PrepareUpdate(release, root, repository, proxyValue, downloadPrefix, progress, cancelDownload.Token));
                if (!window.IsVisible || cancelDownload.IsCancellationRequested) return;
                if (!canInstall()) throw new IOException("游戏或服务已启动，更新尚未安装；请退出后重试。");
                string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
                Process.Start(new ProcessStartInfo(powershell, "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + Path.Combine(session, "Apply-Update.ps1") + "\" -Plan \"" + Path.Combine(session, "plan.json") + "\"") {
                    UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = session, WindowStyle = ProcessWindowStyle.Hidden });
                installing = false; window.Close(); owner.Close();
            } catch (Exception error) { if (window.IsVisible) status.Text = error is IOException || error is InvalidDataException ? error.Message : "下载或启动更新助手失败，程序尚未替换。请检查网络、磁盘空间和权限。"; }
            finally { installing = false; cancelDownload.Dispose(); cancelDownload = null; if (window.IsVisible) { check.IsEnabled = true; install.IsEnabled = true; download.IsEnabled = true; } }
        };
        check.Click += async delegate {
            check.IsEnabled = false; download.IsEnabled = install.IsEnabled = false; release = null;
            try {
                string proxyValue = proxy.Text.Trim(), prefixValue = ValidatePrefix(prefix.Text);
                bool includePreviews = previews.IsChecked == true;
                status.Text = "正在查询版本……"; notes.Text = "";
                var found = await Task.Run(() => Check(repository, includePreviews, proxyValue, prefixValue));
                if (!window.IsVisible) return;
                File.WriteAllText(settings, new JavaScriptSerializer().Serialize(new { http_proxy = proxyValue, download_prefix = prefixValue, previews = includePreviews }), new UTF8Encoding(false));
                release = found; downloadPrefix = prefixValue;
                int comparison = CompareVersions(found.Version, version);
                status.Text = comparison > 0 ? "发现新版本：" + found.Version : comparison == 0 ? "已是当前频道最新版本。" : "本机版本高于当前发布版本，无需更新。";
                notes.Text = "发布版本：" + found.Version + "\n\n" + found.Notes;
                download.IsEnabled = comparison > 0;
                install.IsEnabled = comparison > 0 && found.VerifiedOrigin && found.Sha256.Length == 64 && found.Size > 0 && found.Size <= 2147483648L;
                if (comparison > 0 && !install.IsEnabled) status.Text += " 自动更新需从 GitHub 核对校验值，可用本机 HTTP 代理重试。";
            } catch (Exception error) { if (window.IsVisible) status.Text = error is ArgumentException || error is IOException || error is InvalidDataException ? error.Message : "更新检查失败，请检查网络或加速地址后重试。"; }
            finally { if (window.IsVisible) check.IsEnabled = true; }
        };
        window.Content = layout; window.ShowDialog();
    }
}
