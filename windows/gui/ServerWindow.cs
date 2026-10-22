// SPDX-License-Identifier: GPL-2.0-or-later
using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

[assembly: System.Reflection.AssemblyTitle("The Hunt Server")]
[assembly: System.Reflection.AssemblyProduct("TheHuntServer")]
[assembly: System.Reflection.AssemblyCompany("iytq")]
[assembly: System.Reflection.AssemblyVersion("0.1.0.0")]

internal sealed class OwnedJob : IDisposable
{
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
        public long ProcessTime, JobTime; public uint Flags; public UIntPtr MinWork, MaxWork;
        public uint ActiveLimit; public UIntPtr Affinity; public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct Counters { public ulong A, B, C, D, E, F; }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
        public BasicLimits Basic; public Counters IO; public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int kind, IntPtr info, uint length);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    private IntPtr handle;
    public OwnedJob() {
        handle = CreateJobObject(IntPtr.Zero, null);
        if (handle == IntPtr.Zero) throw new Win32Exception();
        var limits = new ExtendedLimits(); limits.Basic.Flags = 0x2000; // KILL_ON_JOB_CLOSE
        int size = Marshal.SizeOf(limits); IntPtr memory = Marshal.AllocHGlobal(size);
        try {
            Marshal.StructureToPtr(limits, memory, false);
            if (!SetInformationJobObject(handle, 9, memory, (uint)size)) throw new Win32Exception();
        } catch { Dispose(); throw; } finally { Marshal.FreeHGlobal(memory); }
    }
    public void Assign(Process process) { if (!AssignProcessToJobObject(handle, process.Handle)) throw new Win32Exception(); }
    public void Dispose() { if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; } }
}

public sealed class AccountRow
{
    public long Id { get; set; } public string Name { get; set; }
    public string Email { get; set; } public string State { get; set; }
}

internal sealed class DesktopManager
{
    private readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    private readonly JavaScriptSerializer json = new JavaScriptSerializer();
    private readonly object pipeLock = new object();
    private readonly Window window;
    private Process worker;
    private OwnedJob job;
    private DispatcherTimer timer;
    private bool busy, polling, closing;
    private Dictionary<string, object> snapshot;
    private string Mode { get { return Get<RadioButton>("NormalMode").IsChecked == true ? "normal" : "bbsc"; } }
    private T Get<T>(string name) where T : class { return (T)window.FindName(name); }
    private static bool Flag(Dictionary<string, object> data, string key) { return data.ContainsKey(key) && Convert.ToBoolean(data[key]); }
    private Dictionary<string, object> ModeState(string mode) {
        if (snapshot == null) return new Dictionary<string, object>();
        return (Dictionary<string, object>)((Dictionary<string, object>)snapshot["modes"])[mode];
    }
    private bool Active(string mode) { var state = ModeState(mode); return Flag(state, "running") || Flag(state, "external"); }
    private bool AnyOwned() { return Flag(ModeState("normal"), "running") || Flag(ModeState("bbsc"), "running"); }
    private void Say(string message, bool error) {
        Get<TextBlock>("MessageText").Text = message;
        Get<TextBlock>("MessageText").Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(error ? "#E1AAA4" : "#CDD4D5"));
    }
    private Dictionary<string, object> Request(string action) { return new Dictionary<string, object> { {"action", action}, {"mode", Mode} }; }

    public DesktopManager() {
        using (var stream = typeof(DesktopManager).Assembly.GetManifestResourceStream("TheHuntServer.Window.xaml"))
            window = (Window)XamlReader.Load(stream);
        string icon = Path.Combine(root, "TheHunt.ico");
        if (File.Exists(icon)) window.Icon = BitmapFrame.Create(new Uri(icon));
        string build = Path.Combine(root, "BUILD-INFO.json");
        if (File.Exists(build)) {
            var info = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(build, Encoding.UTF8));
            Get<TextBlock>("VersionText").Text = "v" + Convert.ToString(info["label"]) + " · Windows x64";
        }
        Get<Button>("ChooseAddress").Click += ChooseAddress;
        Get<TextBox>("AddressBox").TextChanged += delegate { UpdateLinks(); };
        Get<RadioButton>("NormalMode").Checked += async delegate { UpdateState(); await RefreshAccounts(); };
        Get<RadioButton>("BbscMode").Checked += async delegate { UpdateState(); await RefreshAccounts(); };
        Get<Button>("StartButton").Click += async delegate { await StartSelected(); };
        Get<Button>("StopButton").Click += async delegate {
            await Work(async delegate { snapshot = (Dictionary<string, object>)await Send(Request("stop")); Say("此模式已停止，账号与数据已保留。", false); });
        };
        foreach (string name in new [] { "Coop", "Web", "Game", "Relay" }) {
            string field = name;
            Get<Button>("Copy" + field).Click += delegate { Copy(Get<TextBox>(field == "Coop" ? "CoopAddress" : field + "Address").Text); };
        }
        Get<Button>("CopyAll").Click += delegate { Copy(AllLinks()); };
        Get<Button>("OpenLogs").Click += delegate { OpenFolder(Path.Combine(root, Mode, "logs")); };
        Get<Button>("OpenBackups").Click += delegate { OpenFolder(Path.Combine(root, "backups", Mode)); };
        Get<Button>("RefreshAccounts").Click += async delegate { await RefreshAccounts(); };
        Get<DataGrid>("AccountGrid").SelectionChanged += delegate { UpdateState(); };
        Get<Button>("CreateAccount").Click += async delegate { await Edit("create"); };
        Get<Button>("RenameAccount").Click += async delegate { await Edit("rename"); };
        Get<Button>("ResetAccount").Click += async delegate { await Edit("reset"); };
        Get<Button>("DeleteAccount").Click += async delegate { await Edit("delete"); };
        Get<Button>("VerifyAccount").Click += async delegate { await Edit("verify"); };
        window.Closing += Closing;
        UpdateState();
    }

    private void StartWorker() {
        string python = Path.Combine(root, @"runtime\bin\python.exe");
        string script = Path.Combine(root, "manager.py");
        if (!File.Exists(python) || !File.Exists(script)) throw new InvalidOperationException("请完整解压 Windows 开服包，再运行 Server.exe。");
        var info = new ProcessStartInfo(python, "-B -u \"" + script + "\"") {
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        info.EnvironmentVariables.Remove("PYTHONHOME"); info.EnvironmentVariables.Remove("PYTHONPATH");
        info.EnvironmentVariables["PYTHONUTF8"] = "1";
        info.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        job = new OwnedJob();
        worker = Process.Start(info);
        try { job.Assign(worker); } catch { worker.Kill(); job.Dispose(); throw; }
        // Drain diagnostics; credentials and requests are never logged or echoed.
        worker.ErrorDataReceived += delegate { };
        worker.BeginErrorReadLine();
    }

    private Task<object> Send(Dictionary<string, object> request) {
        return Task.Run<object>(delegate {
            lock (pipeLock) {
                if (worker == null || worker.HasExited) throw new InvalidOperationException("后台管理进程已退出，请关闭后重新打开管理窗口。");
                // ASCII JSON also works when the Windows stdin code page cannot represent Chinese.
                var text = new StringBuilder();
                foreach (char c in json.Serialize(request)) text.Append(c > 127 ? "\\u" + ((int)c).ToString("x4") : c.ToString());
                worker.StandardInput.WriteLine(text.ToString()); worker.StandardInput.Flush();
                string line = worker.StandardOutput.ReadLine();
                if (line == null) throw new InvalidOperationException("后台管理进程已退出，请查看日志或重新打开窗口。");
                var response = json.Deserialize<Dictionary<string, object>>(line);
                if (!Flag(response, "ok")) throw new InvalidOperationException(Convert.ToString(response["error"]));
                return response["data"];
            }
        });
    }

    private async Task Work(Func<Task> action) {
        if (busy || closing) return;
        busy = true; UpdateState();
        try { await action(); }
        catch (Exception error) { if (!closing) Say(error.Message, true); }
        finally { busy = false; if (!closing) UpdateState(); }
    }

    private async Task StartSelected() {
        await Work(async delegate {
            Say("正在检查地址并启动服务……", false);
            var configure = Request("configure");
            configure["address"] = Get<TextBox>("AddressBox").Text.Trim();
            // A second mode uses the address already held by the first mode.
            if (!Active("normal") && !Active("bbsc")) await Send(configure);
            snapshot = (Dictionary<string, object>)await Send(Request("start"));
            Say("服务已就绪。将连接信息发送给同伴，再到「联机账号」创建各自的账号。", false);
        });
        await RefreshAccounts();
    }

    private async Task Poll() {
        if (busy || polling || closing) return;
        polling = true;
        try {
            snapshot = (Dictionary<string, object>)await Send(Request("status"));
            UpdateState();
        } catch (Exception error) { if (!closing) Say(error.Message, true); }
        finally { polling = false; }
    }

    private async Task RefreshAccounts() {
        if (worker == null || busy || closing) return;
        await Work(async delegate {
            var rows = (IEnumerable)await Send(Request("accounts"));
            var list = new List<AccountRow>();
            foreach (Dictionary<string, object> row in rows) list.Add(new AccountRow {
                Id = Convert.ToInt64(row["id"]), Name = Convert.ToString(row["name"]),
                Email = Convert.ToString(row["email"]), State = Convert.ToString(row["state"])
            });
            Get<DataGrid>("AccountGrid").ItemsSource = list;
        });
    }

    private void UpdateState() {
        bool alive = worker != null && !worker.HasExited;
        bool running = Flag(ModeState(Mode), "running"), external = Flag(ModeState(Mode), "external");
        bool any = Active("normal") || Active("bbsc");
        Get<Panel>("ModePanel").IsEnabled = !busy;
        Get<TextBox>("AddressBox").IsEnabled = !busy && !any;
        Get<Button>("ChooseAddress").IsEnabled = !busy && !any;
        Get<Button>("StartButton").IsEnabled = alive && !busy && !running && !external;
        Get<Button>("StopButton").IsEnabled = alive && !busy && running;
        bool selected = Get<DataGrid>("AccountGrid").SelectedItem != null;
        Get<Button>("CreateAccount").IsEnabled = alive && !busy && running;
        Get<Button>("VerifyAccount").IsEnabled = alive && !busy && selected;
        foreach (string name in new [] { "RenameAccount", "ResetAccount", "DeleteAccount" })
            Get<Button>(name).IsEnabled = alive && !busy && selected && !running && !external;
        Get<Button>("RefreshAccounts").IsEnabled = alive && !busy;
        string error = ModeState(Mode).ContainsKey("error") ? Convert.ToString(ModeState(Mode)["error"]) : "";
        string state = busy ? "● 正在处理…" : external ? "● 外部窗口占用" : running ? (Flag(ModeState(Mode), "ready") ? "● 已就绪" : "● 接口未响应") : error != "" ? "● 异常退出" : "● 未启动";
        Get<TextBlock>("StatusText").Text = state;
        Get<TextBlock>("StatusText").Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(running && Flag(ModeState(Mode), "ready") ? "#ACCCB4" : error != "" ? "#DEA49C" : "#ADB8BF"));
        if (error != "" && !busy) Say(error, true);
        UpdateLinks();
    }

    private void UpdateLinks() {
        string address = Get<TextBox>("AddressBox").Text.Trim(); bool seamless = Mode == "bbsc";
        Get<TextBox>("CoopAddress").Text = address + (seamless ? ":31413" : ":31313");
        Get<TextBox>("WebAddress").Text = "http://" + address + (seamless ? ":31415" : ":31315");
        Get<TextBox>("GameAddress").Text = "http://" + address + ":20443";
        Get<TextBox>("RelayAddress").Text = address + ":20444";
        Get<Grid>("GameRow").Visibility = Get<Grid>("RelayRow").Visibility = seamless ? Visibility.Visible : Visibility.Collapsed;
        Get<TextBlock>("ClientHint").Text = seamless ? "填写位置：The Hunt → 游戏与联机。两位玩家使用不同账号，地址填写同一套。" : "填写位置：普通版启动器 → 在线合作 → shadNet server。留言、血迹等游戏服务保留原有地址。";
        Get<TextBlock>("PortHint").Text = seamless ? "需要放行 TCP 31413、31415、20443、20444，以及 UDP 31414。适用于一组可信玩家。" : "需要放行 TCP 31313、31315，以及 UDP 31314。普通账号与无缝账号分别保存在本机。";
        Get<TextBlock>("AddressHint").Text = address.StartsWith("127.") ? "仅限本机连接。双机游玩时，先选择这台电脑的局域网或 VPN 地址。" : "两台客户端都填写这台开服电脑的地址。使用 Tailscale 等虚拟局域网时，请保持网络连接。";
    }

    private string AllLinks() {
        string text = (Mode == "bbsc" ? "BBSC 无缝联机" : "普通联机") + "\r\n\r\nshadNet 合作服务器：\r\n" + Get<TextBox>("CoopAddress").Text +
            "\r\n\r\nshadNet WebAPI：\r\n" + Get<TextBox>("WebAddress").Text;
        if (Mode == "bbsc") text += "\r\n\r\nBBSC 游戏服务器：\r\n" + Get<TextBox>("GameAddress").Text + "\r\n\r\nBBSC Relay：\r\n" + Get<TextBox>("RelayAddress").Text;
        return text + "\r\n\r\n每位玩家使用不同的本地联机账号。";
    }
    private void Copy(string text) { try { Clipboard.SetText(text); Say("已复制。", false); } catch { Say("剪贴板暂时被占用，请重试。", true); } }
    private void OpenFolder(string path) { try { Directory.CreateDirectory(path); Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); } catch (Exception error) { Say(error.Message, true); } }

    private void ChooseAddress(object sender, RoutedEventArgs args) {
        var menu = new ContextMenu { Background = new SolidColorBrush(Color.FromRgb(34, 39, 44)), Foreground = Brushes.White };
        var seen = new HashSet<string>();
        foreach (var adapter in NetworkInterface.GetAllNetworkInterfaces()) {
            if (adapter.OperationalStatus != OperationalStatus.Up) continue;
            foreach (var item in adapter.GetIPProperties().UnicastAddresses) {
                if (item.Address.AddressFamily != AddressFamily.InterNetwork) continue;
                string address = item.Address.ToString(); if (!seen.Add(address)) continue;
                var choice = new MenuItem { Header = address + "   ·   " + adapter.Name };
                choice.Click += delegate { Get<TextBox>("AddressBox").Text = address; };
                menu.Items.Add(choice);
            }
        }
        menu.PlacementTarget = Get<Button>("ChooseAddress"); menu.IsOpen = true;
    }

    private async Task Edit(string action) {
        var selected = Get<DataGrid>("AccountGrid").SelectedItem as AccountRow;
        if (action != "create" && selected == null) return;
        var data = AccountDialog.Show(window, action, selected);
        if (data == null) return;
        await Work(async delegate {
            var request = Request(action);
            if (selected != null) { request["id"] = selected.Id; request["expected"] = selected.Name; }
            foreach (var item in data) request[item.Key] = item.Value;
            Say("正在处理账号……", false);
            var result = (Dictionary<string, object>)await Send(request);
            Say(Convert.ToString(result["message"]) + (result.ContainsKey("backup") ? " 已保存修改前的数据库备份。" : ""), false);
        });
        await RefreshAccounts();
    }

    private void Closing(object sender, CancelEventArgs args) {
        if (closing) return;
        if ((AnyOwned() || busy) && MessageBox.Show(window, "关闭窗口将停止本窗口启动的服务及当前操作。确定关闭吗？", "The Hunt Server", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) { args.Cancel = true; return; }
        closing = true;
        if (timer != null) timer.Stop();
        if (worker != null && !worker.HasExited) {
            try { worker.StandardInput.Close(); worker.WaitForExit(2500); } catch { }
        }
        if (job != null) job.Dispose(); // Also handles an unresponsive or abruptly closed worker.
    }

    public int Show(Application application, bool test) {
        if (test) {
            window.WindowStartupLocation = WindowStartupLocation.Manual;
            window.Left = -20000; window.Top = -20000;
            window.ShowInTaskbar = false; window.ShowActivated = false;
        }
        window.Loaded += async delegate {
            try {
                StartWorker();
                snapshot = (Dictionary<string, object>)await Send(Request("status"));
                Get<TextBox>("AddressBox").Text = Convert.ToString(snapshot["address"]);
                UpdateState(); await RefreshAccounts();
                if (test) {
                    if (!Get<Button>("StartButton").IsEnabled) throw new InvalidOperationException("Start UI state incorrect");
                    await StartSelected();
                    if (!Flag(ModeState("bbsc"), "ready") || !Get<Button>("StopButton").IsEnabled) throw new InvalidOperationException("Running UI state incorrect");
                    if (Get<DataGrid>("AccountGrid").Items.Count != 1) throw new InvalidOperationException("GUI account list did not load backend data");
                    Get<DataGrid>("AccountGrid").SelectedIndex = 0;
                    if (Get<Button>("DeleteAccount").IsEnabled || !Get<Button>("VerifyAccount").IsEnabled) throw new InvalidOperationException("Live account controls incorrect");
                    if (!AllLinks().Contains("http://127.0.0.1:20443") || !AllLinks().Contains("127.0.0.1:20444")) throw new InvalidOperationException("Connection fields incorrect");
                    window.UpdateLayout();
                    var bitmap = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32);
                    bitmap.Render(window);
                    var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
                    using (var file = File.Create(Path.Combine(root, "gui-test.png"))) encoder.Save(file);
                    snapshot = (Dictionary<string, object>)await Send(Request("stop")); UpdateState();
                    if (!Get<Button>("RenameAccount").IsEnabled || !Get<Button>("DeleteAccount").IsEnabled) throw new InvalidOperationException("Offline account controls incorrect");
                    closing = true; job.Dispose(); application.Shutdown(0); return;
                }
                timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
                timer.Tick += async delegate { await Poll(); }; timer.Start();
            } catch (Exception error) {
                if (test) { Console.Error.WriteLine(error.ToString()); closing = true; if (job != null) job.Dispose(); application.Shutdown(1); }
                else { Say(error.Message, true); UpdateState(); }
            }
        };
        return application.Run(window);
    }

    public void Validate(string capture) {
        foreach (string name in new [] { "StartButton", "StopButton", "CopyAll", "CreateAccount", "RenameAccount", "ResetAccount", "DeleteAccount", "VerifyAccount" })
            if (Get<Button>(name) == null) throw new InvalidOperationException("Missing UI control: " + name);
        var body = Get<Grid>("Body");
        body.Background = window.Background;
        body.Measure(new Size(950, 700)); body.Arrange(new Rect(0, 0, 950, 700)); body.UpdateLayout();
        if (capture != null) {
            var bitmap = new RenderTargetBitmap(1010, 760, 96, 96, PixelFormats.Pbgra32); bitmap.Render(body);
            var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using (var output = File.Create(capture)) encoder.Save(output);
        }
    }

    public async Task LifecycleTest() {
        StartWorker();
        try {
            var config = Request("configure"); config["address"] = "127.0.0.1";
            var start = Request("start");
            await Send(config).ConfigureAwait(false);
            snapshot = (Dictionary<string, object>)await Send(start).ConfigureAwait(false);
            if (!Flag(ModeState("bbsc"), "running")) throw new InvalidOperationException("GUI worker did not start service");
            // Deliberately close the Job while services are active: no descendants may survive.
        } finally { job.Dispose(); }
    }
}

internal static class AccountDialog
{
    public static Dictionary<string, object> Show(Window owner, string action, AccountRow account) {
        string title = new Dictionary<string, string> { {"create","新建账号"}, {"rename","修改账号名"}, {"reset","重置密码"}, {"delete","删除账号"}, {"verify","验证密码"} }[action];
        var dialog = new Window { Owner = owner, Title = title, Width = 460, SizeToContent = SizeToContent.Height,
            ResizeMode = ResizeMode.NoResize, WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Background = owner.Background, Foreground = owner.Foreground, FontFamily = owner.FontFamily, FontSize = 13 };
        dialog.Resources.MergedDictionaries.Add(owner.Resources);
        var panel = new StackPanel { Margin = new Thickness(25) }; dialog.Content = panel;
        panel.Children.Add(new TextBlock { Text = title, FontSize = 21, Margin = new Thickness(0,0,0,16) });
        if (account != null) panel.Children.Add(new TextBlock { Text = "当前账号：" + account.Name + "  ·  ID " + account.Id, Margin = new Thickness(0,0,0,14) });
        var fields = new Dictionary<string, Control>();
        Action<string,string,bool> field = delegate(string key, string label, bool secret) {
            panel.Children.Add(new TextBlock { Text = label, Margin = new Thickness(0,9,0,5), TextWrapping = TextWrapping.Wrap });
            Control box = secret ? (Control)new PasswordBox { MaxLength = 256 } : new TextBox { MaxLength = 256 };
            fields[key] = box; panel.Children.Add(box);
        };
        if (action == "create") {
            field("name", "账号（3–16 位英文字母、数字、_ 或 -）", false);
            field("email", "邮箱（选填；留空自动生成，不发送验证邮件）", false);
        }
        if (action == "rename") field("value", "新的账号名；ID 和密码保持不变", false);
        if (action == "delete") field("value", "请输入完整账号名确认删除。只删除此模式的联机账号，不改玩家存档。", false);
        if (action == "create" || action == "reset" || action == "verify") field("password", action == "reset" ? "新密码" : "密码", true);
        if (action == "create" || action == "reset") field("repeat", "重复密码", true);
        var notice = new TextBlock { Foreground = new SolidColorBrush(Color.FromRgb(225,170,164)), TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0,12,0,0) }; panel.Children.Add(notice);
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0,18,0,0) };
        var cancel = new Button { Content = "取消", IsCancel = true, Margin = new Thickness(0,0,8,0) };
        var submit = new Button { Content = action == "delete" ? "确认删除" : "确认", IsDefault = true };
        buttons.Children.Add(cancel); buttons.Children.Add(submit); panel.Children.Add(buttons);
        Dictionary<string, object> result = null;
        submit.Click += delegate {
            Func<string,string> value = key => fields[key] is PasswordBox ? ((PasswordBox)fields[key]).Password : ((TextBox)fields[key]).Text.Trim();
            if (action == "create" || action == "rename") {
                string name = value(action == "create" ? "name" : "value");
                if (!System.Text.RegularExpressions.Regex.IsMatch(name, "^[A-Za-z0-9_-]{3,16}$") || name == "DeletedUser") { notice.Text = "账号格式不正确，请使用 3–16 位英文字母、数字、_ 或 -。"; return; }
                var grid = (DataGrid)owner.FindName("AccountGrid");
                foreach (AccountRow row in grid.Items) {
                    if (String.Equals(row.Name, name, StringComparison.OrdinalIgnoreCase) && (action == "create" || row.Id != account.Id)) { notice.Text = "此账号名已被使用。"; return; }
                }
            }
            if (fields.ContainsKey("repeat") && value("repeat") != value("password")) { notice.Text = "两次输入的密码不同。"; return; }
            if (fields.ContainsKey("password") && value("password").Length == 0) { notice.Text = "密码不能为空。"; return; }
            if (action == "delete" && value("value") != account.Name) { notice.Text = "输入的账号名不匹配。"; return; }
            result = new Dictionary<string, object>();
            foreach (var entry in fields) if (entry.Key != "repeat") result[entry.Key] = value(entry.Key);
            if (action == "reset") { result["value"] = result["password"]; result.Remove("password"); }
            dialog.DialogResult = true;
        };
        dialog.ShowDialog();
        foreach (var box in fields.Values) { if (box is PasswordBox) ((PasswordBox)box).Clear(); }
        return result;
    }
}

internal static class Entry
{
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);
    [STAThread]
    public static int Main(string[] args) {
        try {
            var application = new Application();
            var manager = new DesktopManager();
            if (args.Length > 0 && args[0] == "--validate") { manager.Validate(args.Length > 1 ? args[1] : null); return 0; }
            if (args.Length > 0 && args[0] == "--test-lifecycle") { manager.LifecycleTest().GetAwaiter().GetResult(); return 0; }
            if (args.Length > 0 && args[0] == "--test-ui") return manager.Show(application, true);
            string identity;
            using (var sha = SHA256.Create()) identity = BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(AppDomain.CurrentDomain.BaseDirectory.ToLowerInvariant()))).Replace("-", "");
            bool created;
            using (var mutex = new Mutex(true, @"Local\TheHuntServer-" + identity, out created)) {
                if (!created) { MessageBox.Show("此目录的管理窗口已经打开，请在任务栏切换到 The Hunt Server。", "The Hunt Server"); return 0; }
                application.Activated += delegate {
                    if (application.MainWindow != null) { int dark = 1; DwmSetWindowAttribute(new System.Windows.Interop.WindowInteropHelper(application.MainWindow).Handle, 20, ref dark, 4); }
                };
                return manager.Show(application, false);
            }
        } catch (Exception error) {
            if (args.Length > 0) Console.Error.WriteLine(error.ToString());
            else MessageBox.Show(error.Message, "The Hunt Server", MessageBoxButton.OK, MessageBoxImage.Error);
            return 1;
        }
    }
}
