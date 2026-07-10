using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

namespace SteamScreenshotBackup
{
    internal enum ThemeMode { System, Dark, Light }

    // Shared look-and-feel for every window in the app. Two Steam-inspired palettes
    // (dark and light) selected by the user's theme setting; "System" follows the
    // Windows app color setting. Windows re-style themselves via the Changed event.
    internal static class Theme
    {
        public static ThemeMode Mode { get; private set; } = ThemeMode.Dark;
        public static event Action Changed;

        private static bool Dark =>
            Mode == ThemeMode.Dark || (Mode == ThemeMode.System && SystemPrefersDark());

        // ----- palette (properties so they always reflect the active mode) -----
        public static Color Background => Dark ? Color.FromArgb(22, 29, 37)    : Color.FromArgb(244, 247, 250);
        // A step subtler than Panel, for alternating rows in lists (distinguishable from
        // both Background and Panel so it never gets mistaken for a section header).
        public static Color RowAlt     => Dark ? Color.FromArgb(27, 35, 45)    : Color.FromArgb(236, 240, 244);
        public static Color Panel      => Dark ? Color.FromArgb(32, 41, 52)    : Color.FromArgb(255, 255, 255);
        public static Color PanelEdge  => Dark ? Color.FromArgb(53, 66, 82)    : Color.FromArgb(208, 216, 224);
        public static Color Text       => Dark ? Color.FromArgb(214, 226, 235) : Color.FromArgb(26, 38, 50);
        public static Color TextDim    => Dark ? Color.FromArgb(126, 143, 158) : Color.FromArgb(108, 122, 136);
        public static Color Accent     => Dark ? Color.FromArgb(102, 192, 244) : Color.FromArgb(22, 106, 158);
        public static Color AccentDark => Dark ? Color.FromArgb(28, 82, 116)   : Color.FromArgb(22, 106, 158);
        public static Color Selection  => Dark ? Color.FromArgb(28, 82, 116)   : Color.FromArgb(203, 228, 245);
        public static Color Warning    => Dark ? Color.FromArgb(233, 185, 91)  : Color.FromArgb(158, 106, 10);
        public static Color Error      => Dark ? Color.FromArgb(232, 106, 100) : Color.FromArgb(184, 42, 36);
        public static Color Success    => Dark ? Color.FromArgb(129, 201, 149) : Color.FromArgb(22, 128, 61);

        public static readonly Font BaseFont   = new Font("Segoe UI", 9.75f);
        public static readonly Font SmallFont  = new Font("Segoe UI", 8.75f);
        public static readonly Font TitleFont  = new Font("Segoe UI Semibold", 14f);
        public static readonly Font HeaderFont = new Font("Segoe UI Semibold", 9f);
        public static readonly Font StatFont   = new Font("Segoe UI Semibold", 16f);

        private static Icon _appIcon;
        public static Icon AppIcon => _appIcon ??= CreateAppIcon();

        public static void SetMode(ThemeMode mode)
        {
            if (Mode == mode) return;
            Mode = mode;
            Changed?.Invoke();
        }

        private static bool SystemPrefersDark()
        {
            try
            {
                using var k = Registry.CurrentUser.OpenSubKey(
                    @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
                return k?.GetValue("AppsUseLightTheme") is int v && v == 0;
            }
            catch { return true; }
        }

        [DllImport("dwmapi.dll", PreserveSig = true)]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

        [DllImport("uxtheme.dll", CharSet = CharSet.Unicode)]
        private static extern int SetWindowTheme(IntPtr hWnd, string appName, string idList);

        // Gives a scrolling control (ListView, TreeView, DataGridView, AutoScroll panel)
        // dark or light native scrollbars/headers that match the active theme, and keeps
        // them in sync when the user switches themes. Safe to call before the handle
        // exists \u2014 it re-applies on HandleCreated \u2014 and self-detaches on dispose.
        public static void ApplyScrollbars(Control c)
        {
            void Apply()
            {
                if (c.IsDisposed || !c.IsHandleCreated) return;
                try { SetWindowTheme(c.Handle, Dark ? "DarkMode_Explorer" : "Explorer", null); } catch { }
            }
            if (c.IsHandleCreated) Apply();
            else c.HandleCreated += (s, e) => Apply();
            Changed += Apply;
            c.Disposed += (s, e) => Changed -= Apply;
        }

        // A DropDownList-style ComboBox's closed display area ignores BackColor/ForeColor
        // entirely (comctl32 theme-draws it) - SetWindowTheme's "DarkMode_*" pseudo-themes
        // don't reliably take effect without the rest of the undocumented dark-mode API set,
        // so the only robust fix is to own the painting: OwnerDrawFixed covers the closed
        // display and every dropdown row: FlatStyle.Flat still supplies the border/arrow.
        public static void StyleComboBox(ComboBox c)
        {
            c.DrawMode = DrawMode.OwnerDrawFixed;
            c.DrawItem += (s, e) =>
            {
                if (e.Index < 0) return;
                bool selected = (e.State & DrawItemState.Selected) != 0;
                Color bg = selected ? Selection : (c.BackColor);
                using (var b = new SolidBrush(bg)) e.Graphics.FillRectangle(b, e.Bounds);
                var r = new Rectangle(e.Bounds.X + 6, e.Bounds.Y, e.Bounds.Width - 6, e.Bounds.Height);
                TextRenderer.DrawText(e.Graphics, c.Items[e.Index].ToString(), c.Font, r, Text,
                    TextFormatFlags.Left | TextFormatFlags.VerticalCenter);
            };
        }

        // DataGridView's scroll bars aren't part of its own window like a native
        // ListView/TreeView's are \u2014 they're separate HScrollBar/VScrollBar child
        // controls with their own handles, so ApplyScrollbars (which themes the
        // control's own handle) never reaches them, leaving them stuck light-themed.
        // Those child controls also come and go as rows are added/removed, so this
        // reacts to ControlAdded as well as re-theming on every theme change.
        public static void ApplyDataGridScrollbars(DataGridView grid)
        {
            void ApplyOne(Control sb)
            {
                void Do() { try { SetWindowTheme(sb.Handle, Dark ? "DarkMode_Explorer" : "Explorer", null); } catch { } }
                if (sb.IsHandleCreated) Do();
                else sb.HandleCreated += (s, e) => Do();
            }
            void ApplyAll()
            {
                if (grid.IsDisposed) return;
                foreach (Control c in grid.Controls)
                    if (c is ScrollBar) ApplyOne(c);
            }
            grid.ControlAdded += (s, e) => { if (e.Control is ScrollBar) ApplyOne(e.Control); };
            ApplyAll();
            Changed += ApplyAll;
            grid.Disposed += (s, e) => Changed -= ApplyAll;
        }

        // ListView (and a few other controls) don't expose DoubleBuffered publicly, so
        // owner-drawn rows repaint directly to screen and visibly flicker on every mouse
        // move over the list. Flip the protected property on instead.
        public static void EnableDoubleBuffer(Control c)
        {
            var prop = typeof(Control).GetProperty("DoubleBuffered",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            prop?.SetValue(c, true, null);
        }

        // Base styling every window goes through: colors, font, icon, matching title bar.
        public static void ApplyWindow(Form f)
        {
            f.BackColor = Background;
            f.ForeColor = Text;
            f.Font = BaseFont;
            f.Icon = AppIcon;
            try
            {
                int on = Dark ? 1 : 0;
                DwmSetWindowAttribute(f.Handle, 20, ref on, 4);   // DWMWA_USE_IMMERSIVE_DARK_MODE
            }
            catch { }
        }

        public static void StyleButton(Button b, bool primary = false)
        {
            b.FlatStyle = FlatStyle.Flat;
            b.FlatAppearance.BorderSize = 1;
            b.FlatAppearance.BorderColor = primary ? Accent : PanelEdge;
            b.BackColor = primary ? AccentDark : Panel;
            b.ForeColor = primary ? Color.White : Text;
            b.FlatAppearance.MouseOverBackColor = primary
                ? ControlPaint.Light(AccentDark, 0.2f)
                : (Dark ? Color.FromArgb(44, 56, 70) : Color.FromArgb(232, 238, 244));
            b.FlatAppearance.MouseDownBackColor = primary
                ? ControlPaint.Dark(AccentDark, 0.1f)
                : (Dark ? Color.FromArgb(26, 34, 43) : Color.FromArgb(214, 224, 233));
            b.UseVisualStyleBackColor = false;
            b.Cursor = Cursors.Hand;
        }

        public static void StyleInput(Control c)
        {
            c.BackColor = Dark ? Color.FromArgb(28, 36, 46) : Color.White;
            c.ForeColor = Text;
        }

        // Renderer so the tray context menu matches the app palette.
        public static ToolStripRenderer MenuRenderer => new MenuColorRenderer();

        private class MenuColorTable : ProfessionalColorTable
        {
            public override Color MenuItemSelected => Selection;
            public override Color MenuItemSelectedGradientBegin => Selection;
            public override Color MenuItemSelectedGradientEnd => Selection;
            public override Color MenuItemBorder => Selection;
            public override Color ToolStripDropDownBackground => Panel;
            public override Color ImageMarginGradientBegin => Panel;
            public override Color ImageMarginGradientMiddle => Panel;
            public override Color ImageMarginGradientEnd => Panel;
            public override Color SeparatorDark => PanelEdge;
            public override Color SeparatorLight => PanelEdge;
            public override Color MenuBorder => PanelEdge;
            public override Color CheckBackground => Selection;
            public override Color CheckSelectedBackground => Selection;
            public override Color CheckPressedBackground => Selection;
        }

        private class MenuColorRenderer : ToolStripProfessionalRenderer
        {
            public MenuColorRenderer() : base(new MenuColorTable()) { }

            protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
            {
                e.TextColor = e.Item.Enabled ? Text : TextDim;
                base.OnRenderItemText(e);
            }

            protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e)
            {
                // Simple themed check mark instead of the stock blue glyph.
                var r = e.ImageRectangle;
                using var pen = new Pen(Accent, 2f);
                e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
                e.Graphics.DrawLines(pen, new[]
                {
                    new PointF(r.Left + 3, r.Top + r.Height / 2f),
                    new PointF(r.Left + r.Width / 2.6f, r.Bottom - 4),
                    new PointF(r.Right - 3, r.Top + 3)
                });
            }
        }

        // The camera glyph used everywhere: tray icon, window icons, headers.
        // Drawn at runtime so the repo needs no binary assets.
        public static Bitmap DrawCamera(int size)
        {
            var bmp = new Bitmap(size, size);
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                float s = size / 32f;
                using var body = new SolidBrush(Color.FromArgb(35, 35, 40));
                g.FillRectangle(body, 2 * s, 9 * s, 28 * s, 19 * s);
                g.FillRectangle(body, 10 * s, 5 * s, 12 * s, 6 * s);
                using var lens = new SolidBrush(Color.FromArgb(102, 192, 244));   // Steam blue
                g.FillEllipse(lens, 9 * s, 12 * s, 14 * s, 14 * s);
                using var inner = new SolidBrush(Color.White);
                g.FillEllipse(inner, 13 * s, 16 * s, 6 * s, 6 * s);
            }
            return bmp;
        }

        private static Icon CreateAppIcon()
        {
            using var bmp = DrawCamera(32);
            return Icon.FromHandle(bmp.GetHicon());
        }
    }

    // A Details-view ListView themed via Theme.ApplyScrollbars (SetWindowTheme
    // "Explorer"/"DarkMode_Explorer") keeps drawing the native header's column
    // divider lines all the way down through the empty space below the last
    // row, the same guide lines Explorer itself shows in an under-full file
    // list. Owner-draw notifications only cover items/subitems, not that empty
    // tail, so the only way to erase them is to paint over that area ourselves
    // right after the native control finishes its own WM_PAINT.
    internal sealed class FlatListView : ListView
    {
        private const int WM_PAINT = 0x000F;

        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if (m.Msg == WM_PAINT) PaintOverEmptyArea();
        }

        private void PaintOverEmptyArea()
        {
            if (!IsHandleCreated || View != View.Details || Items.Count == 0) return;
            int top = Items[Items.Count - 1].Bounds.Bottom;
            int height = ClientSize.Height - top;
            if (height <= 0) return;
            using var g = Graphics.FromHwnd(Handle);
            using var b = new SolidBrush(Theme.Background);
            g.FillRectangle(b, 0, top, ClientSize.Width, height);
        }
    }
}
