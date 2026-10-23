using System;
using System.Diagnostics;
using System.Reflection;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

public static class StartupCheckTest {
    static readonly MethodInfo Watch = typeof(HuntUpdates).GetMethod("WatchStartupCore", BindingFlags.Static | BindingFlags.NonPublic);
    static void Require(bool value, string message) { if (!value) throw new Exception(message); }
    static void Pump(Func<bool> done) {
        var frame = new DispatcherFrame(); var clock = Stopwatch.StartNew();
        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(10) };
        timer.Tick += delegate { if (done() || clock.ElapsedMilliseconds > 5000) frame.Continue = false; };
        timer.Start(); Dispatcher.PushFrame(frame); timer.Stop();
        Require(done(), "Timed out pumping the UI dispatcher");
    }
    static Window Make(Button button) {
        return new Window { Content = button, Width = 240, Height = 80,
            Left = -20000, Top = -20000, ShowActivated = false, ShowInTaskbar = false };
    }
    [STAThread] public static int Main() {
        try {
            SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext());
            foreach (string result in new [] { "new", "same", "failure", "closed" }) {
                var button = new Button { Content = "Check" }; var window = Make(button);
                int calls = 0, queryThread = 0, uiThread = Thread.CurrentThread.ManagedThreadId;
                using (var gate = new ManualResetEvent(false)) {
                    Func<HuntRelease> query = () => {
                        Interlocked.Increment(ref calls); queryThread = Thread.CurrentThread.ManagedThreadId;
                        Require(gate.WaitOne(5000), "Background query was not released");
                        if (result == "failure") throw new System.IO.IOException("offline");
                        return new HuntRelease { Version = result == "same" ? "0.1.0-preview.7" : "0.1.0-preview.8" };
                    };
                    Watch.Invoke(null, new object[] { window, button, "0.1.0-preview.7", query });
                    window.Show(); Pump(() => Volatile.Read(ref calls) == 1);
                    bool responsive = false;
                    window.Dispatcher.BeginInvoke(new Action(() => responsive = true));
                    Pump(() => responsive);
                    Require(queryThread != uiThread, "Network query ran on the UI thread");
                    typeof(Window).GetMethod("OnContentRendered", BindingFlags.Instance | BindingFlags.NonPublic)
                        .Invoke(window, new object[] { EventArgs.Empty });
                    Require(calls == 1, "Window render started a second query");
                    if (result == "closed") window.Close();
                    gate.Set();
                    if (result == "closed") {
                        bool drained = false;
                        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(150) };
                        timer.Tick += delegate { drained = true; timer.Stop(); };
                        timer.Start(); Pump(() => drained);
                        Require(button.ToolTip == null && (string)button.Content == "Check", "Closed window was modified");
                    } else {
                        Pump(() => button.ToolTip != null);
                        Require((string)button.Content == (result == "new" ? "发现新版" : "Check"), "Wrong version indicator");
                        if (result == "new") Require(button.ToolTip.ToString().Contains("0.1.0-preview.8"), "Version missing from tooltip");
                        window.Close();
                    }
                    Require(calls == 1, "Query was repeated");
                }
            }
            Console.WriteLine("PASS: responsive startup, one query per window, new/current/offline states and safe close while checking");
            return 0;
        } catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
