# -*- coding: utf-8 -*-
"""
DLC Tab Designer v1.1.0

Rename this tab and arrange its buttons (Large / Small stacked / in a More
menu), then refresh pyRevit - without closing Revit. Finds its extension
from its own location, so it works wherever the extension is copied.

IronPython 2.7 / pyRevit.
"""
__title__ = "Tab\nDesigner"
__author__ = "DLC"
__doc__ = ("Rename the tab and arrange its buttons: large, small (stacked) "
           "or in a More menu. Applies and refreshes pyRevit.")

import os

from pyrevit import forms

from dlc_tabdesigner import engine

HERE = os.path.dirname(os.path.abspath(__file__))
MORE_ICON = os.path.join(HERE, "more_icon.png")
MORE_ICON_DARK = os.path.join(HERE, "more_icon.dark.png")
BACKUPS = engine.default_backup_dir()

XAML = u"""<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="DLC Tab Designer" Width="960" Height="660" MinWidth="780"
    MinHeight="500" WindowStartupLocation="CenterScreen"
    FontFamily="Segoe UI" FontSize="12" Background="#F5F7FA"
    ShowInTaskbar="False">
  <Window.Resources>
    <Style TargetType="Button">
      <Setter Property="Padding" Value="12,5"/>
      <Setter Property="MinWidth" Value="70"/>
    </Style>
    <Style x:Key="Card" TargetType="Border">
      <Setter Property="Background" Value="White"/>
      <Setter Property="BorderBrush" Value="#DDE2E8"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="CornerRadius" Value="6"/>
    </Style>
  </Window.Resources>
  <DockPanel Margin="16">

    <Border DockPanel.Dock="Top" Style="{StaticResource Card}"
            Padding="14,10" Margin="0,0,0,12">
      <StackPanel>
        <StackPanel Orientation="Horizontal">
          <TextBlock Text="Tab name" VerticalAlignment="Center"
                     FontWeight="SemiBold" Width="76"/>
          <TextBox x:Name="tab_name" Width="150" Padding="4,3"
                   VerticalContentAlignment="Center"/>
          <CheckBox x:Name="rename_ext" Margin="18,0,0,0"
                    VerticalAlignment="Center"/>
        </StackPanel>
        <TextBlock x:Name="where" Foreground="#64748B" Margin="0,8,0,0"
                   TextTrimming="CharacterEllipsis"/>
      </StackPanel>
    </Border>

    <DockPanel DockPanel.Dock="Bottom" Margin="0,12,0,0" LastChildFill="False">
      <Button x:Name="btn_suggest" Content="Suggest compact layout"
              DockPanel.Dock="Left"/>
      <Button x:Name="btn_colors" Content="Auto colours"
              DockPanel.Dock="Left" Margin="6,0,0,0"/>
      <Button x:Name="btn_reset" Content="Reset to current"
              DockPanel.Dock="Left" Margin="6,0,0,0"/>
      <Button x:Name="btn_undo" Content="Undo last apply..."
              DockPanel.Dock="Left" Margin="6,0,0,0"/>
      <Button x:Name="btn_backups" Content="Backups folder"
              DockPanel.Dock="Left" Margin="6,0,0,0"/>
      <Button x:Name="btn_close" Content="Close" IsCancel="True"
              DockPanel.Dock="Right"/>
      <Button x:Name="btn_apply" Content="Apply and refresh"
              IsDefault="True" DockPanel.Dock="Right" Margin="0,0,6,0"
              Background="#2563EB" Foreground="White" BorderBrush="#1D4ED8"
              FontWeight="SemiBold"/>
    </DockPanel>
    <StackPanel DockPanel.Dock="Bottom" Orientation="Horizontal"
                Margin="2,10,0,0">
      <CheckBox x:Name="opt_refresh" Content="Refresh pyRevit after applying"
                IsChecked="True"/>
      <CheckBox x:Name="opt_fix" Margin="20,0,0,0"
                Content="Also update old folder names written inside files"/>
    </StackPanel>

    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="210"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <Border Style="{StaticResource Card}" Margin="0,0,12,0">
        <DockPanel>
          <TextBlock DockPanel.Dock="Top" Text="PANELS" Margin="12,10,0,6"
                     Foreground="#64748B" FontWeight="SemiBold" FontSize="11"/>
          <ListBox x:Name="panel_list" BorderThickness="0" Margin="4,0,4,6"/>
        </DockPanel>
      </Border>
      <Border Grid.Column="1" Style="{StaticResource Card}">
        <DockPanel Margin="14,10,14,12">
          <DockPanel DockPanel.Dock="Top" Margin="0,0,0,8">
            <TextBlock x:Name="panel_title" FontSize="16" FontWeight="SemiBold"
                       DockPanel.Dock="Left"/>
            <TextBlock x:Name="panel_hint" Foreground="#64748B"
                       VerticalAlignment="Bottom" HorizontalAlignment="Right"/>
          </DockPanel>
          <StackPanel DockPanel.Dock="Top" Orientation="Horizontal"
                      Margin="0,0,0,10">
            <TextBlock Text="Title colour" VerticalAlignment="Center"
                       FontWeight="SemiBold" Width="84"/>
            <WrapPanel x:Name="swatches" VerticalAlignment="Center"/>
          </StackPanel>
          <Border DockPanel.Dock="Bottom" Background="#EEF2F7"
                  CornerRadius="4" Padding="10,8" Margin="0,10,0,0">
            <StackPanel>
              <TextBlock Text="Ribbon preview" Foreground="#64748B"
                         FontSize="11"/>
              <WrapPanel x:Name="preview" Margin="0,6,0,0"/>
              <Border x:Name="preview_strip" CornerRadius="3" Padding="0,2"
                      Margin="0,0,6,0">
                <TextBlock x:Name="preview_strip_text" FontSize="11"
                           HorizontalAlignment="Center"/>
              </Border>
            </StackPanel>
          </Border>
          <ScrollViewer VerticalScrollBarVisibility="Auto">
            <Grid x:Name="tools"/>
          </ScrollViewer>
        </DockPanel>
      </Border>
    </Grid>
  </DockPanel>
</Window>"""


def _wpf():
    import clr
    for asm in ("PresentationFramework", "PresentationCore", "WindowsBase"):
        try:
            clr.AddReference(asm)
        except Exception:
            pass
    from System.Windows import (Thickness, GridLength, GridUnitType,
                                FontWeights, VerticalAlignment,
                                HorizontalAlignment, CornerRadius,
                                TextWrapping, TextAlignment)
    from System.Windows.Controls import Orientation
    from System.Windows import Controls
    from System.Windows.Media import SolidColorBrush, Color, Brushes
    return dict(Thickness=Thickness, GridLength=GridLength,
                GridUnitType=GridUnitType, FontWeights=FontWeights,
                VA=VerticalAlignment, HA=HorizontalAlignment,
                CornerRadius=CornerRadius, C=Controls, TextWrapping=TextWrapping,
                TextAlignment=TextAlignment, Orientation=Orientation,
                SolidColorBrush=SolidColorBrush, Color=Color, Brushes=Brushes)


def brush(w, hexcode):
    h = hexcode.lstrip("#")
    if len(h) == 8:
        return w["SolidColorBrush"](w["Color"].FromArgb(
            int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16),
            int(h[6:8], 16)))
    return w["SolidColorBrush"](w["Color"].FromRgb(
        int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


def pick_custom_color(current):
    """Windows colour picker. Returns '#RRGGBB' or None if cancelled."""
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import ColorDialog, DialogResult
    from System.Drawing import ColorTranslator
    dlg = ColorDialog()
    dlg.FullOpen = True
    if current:
        try:
            dlg.Color = ColorTranslator.FromHtml(current[-7:] if
                                                 len(current) == 9 else current)
        except Exception:
            pass
    if dlg.ShowDialog() == DialogResult.OK:
        c = dlg.Color
        return "#%02X%02X%02X" % (c.R, c.G, c.B)
    return None


class DesignerWindow(forms.WPFWindow):
    def __init__(self, design):
        try:
            forms.WPFWindow.__init__(self, XAML, literal_string=True)
        except TypeError:   # older pyRevit: needs a file
            import io
            import tempfile
            path = os.path.join(tempfile.gettempdir(), "dlc_tab_designer.xaml")
            with io.open(path, "w", encoding="utf-8") as fh:
                fh.write(XAML)
            forms.WPFWindow.__init__(self, path)
        self.w = _wpf()
        self.design = design
        self.do_reload = False
        ctx = design.ctx
        self.tab_name.Text = ctx.tab_name
        self.where.Text = u"Extension found at:  %s" % ctx.ext_dir
        self.rename_ext.IsChecked = True
        self.tab_name.TextChanged += lambda s, e: self._sync_ext_label()
        self._sync_ext_label()
        self.panel_list.SelectionChanged += self._panel_changed
        self.btn_suggest.Click += self._suggest
        self.btn_colors.Click += self._auto_colors
        self.btn_reset.Click += self._reset
        self.btn_undo.Click += self._undo
        self.btn_backups.Click += self._open_backups
        self.btn_apply.Click += self._apply
        self._fill_panels()

    # ------------------------------------------------------------ header
    def _sync_ext_label(self):
        new = (self.tab_name.Text or u"").strip() or u"?"
        cur = os.path.basename(self.design.ctx.ext_dir)
        target = new + u".extension"
        if target.lower() == cur.lower():
            self.rename_ext.Content = u"Extension folder already named %s" % cur
            self.rename_ext.IsEnabled = False
        else:
            self.rename_ext.Content = u"Rename extension folder too  (%s → %s)" \
                % (cur, target)
            self.rename_ext.IsEnabled = True

    # ------------------------------------------------------------ panels
    def _fill_panels(self):
        keep = self.design.index
        self.panel_list.Items.Clear()
        for p in self.design.panels:
            self.panel_list.Items.Add(self._panel_row(p))
        if self.design.panels:
            self.panel_list.SelectedIndex = max(0, keep)
        self._render()

    def _panel_row(self, p):
        w = self.w
        C = w["C"]
        row = C.StackPanel()
        row.Orientation = w["Orientation"].Horizontal
        dot = C.Border()
        dot.Width = dot.Height = 11
        dot.CornerRadius = w["CornerRadius"](2)
        dot.Margin = w["Thickness"](0, 0, 7, 0)
        dot.VerticalAlignment = w["VA"].Center
        if p.color:
            dot.Background = brush(w, p.color)
        else:
            dot.BorderBrush = brush(w, "#CBD5E1")
            dot.BorderThickness = w["Thickness"](1)
        row.Children.Add(dot)
        t = C.TextBlock()
        t.Text = u"%s   (%d)" % (p.label, len(p.items))
        row.Children.Add(t)
        row.Tag = p.label
        return row

    def _refresh_panel_row(self):
        i = self.design.index
        if 0 <= i < self.panel_list.Items.Count:
            self.panel_list.Items[i] = self._panel_row(self.design.panel)
            self.panel_list.SelectedIndex = i

    def _panel_changed(self, sender, args):
        if self.panel_list.SelectedIndex >= 0:
            self.design.index = self.panel_list.SelectedIndex
            self._render()

    # ------------------------------------------------------------ tools grid
    def _text(self, txt, row, col, bold=False, gray=False):
        w = self.w
        tb = w["C"].TextBlock()
        tb.Text = txt
        tb.VerticalAlignment = w["VA"].Center
        tb.Margin = w["Thickness"](4, 5, 8, 5)
        if bold:
            tb.FontWeight = w["FontWeights"].SemiBold
        if gray:
            tb.Foreground = brush(w, "#64748B")
        w["C"].Grid.SetRow(tb, row)
        w["C"].Grid.SetColumn(tb, col)
        self.tools.Children.Add(tb)
        return tb

    def _render(self):
        w = self.w
        C = w["C"]
        g = self.tools
        g.Children.Clear()
        g.RowDefinitions.Clear()
        g.ColumnDefinitions.Clear()
        p = self.design.panel
        if p is None:
            self.panel_title.Text = u"No panels found"
            return
        self.panel_title.Text = p.label
        self._render_swatches()
        self.panel_hint.Text = u"%d tools · order = left to right" \
            % len(p.items)
        for width, star in ((1, True), (190, False), (34, False), (34, False)):
            cd = C.ColumnDefinition()
            cd.Width = w["GridLength"](width, w["GridUnitType"].Star if star
                                       else w["GridUnitType"].Pixel)
            g.ColumnDefinitions.Add(cd)
        for _ in range(len(p.items) + 1):
            rd = C.RowDefinition()
            rd.Height = w["GridLength"].Auto
            g.RowDefinitions.Add(rd)
        self._text(u"Tool", 0, 0, bold=True, gray=True)
        self._text(u"Size on the ribbon", 0, 1, bold=True, gray=True)
        for r, it in enumerate(p.items):
            row = r + 1
            label = it.label + (u"   (this tool)" if it.locked else u"")
            self._text(label, row, 0)
            combo = C.ComboBox()
            combo.Margin = w["Thickness"](0, 3, 6, 3)
            opts = it.options()
            for o in opts:
                combo.Items.Add(engine.MODE_LABELS[o])
            combo.SelectedIndex = opts.index(it.mode) if it.mode in opts else 0
            combo.IsEnabled = len(opts) > 1
            if not combo.IsEnabled:
                combo.ToolTip = (u"Special button - stays as it is" if
                                 it.kind in engine.FIXED_KINDS else
                                 u"The designer can't move itself while it "
                                 u"runs")
            combo.SelectionChanged += self._mode_handler(it, opts, combo)
            C.Grid.SetRow(combo, row)
            C.Grid.SetColumn(combo, 1)
            g.Children.Add(combo)
            for col, (sym, delta) in enumerate(((u"▲", -1),
                                                (u"▼", 1))):
                b = C.Button()
                b.Content = sym
                b.MinWidth = 0
                b.Padding = w["Thickness"](0)
                b.Margin = w["Thickness"](2, 3, 2, 3)
                b.IsEnabled = (r > 0) if delta < 0 else (r < len(p.items) - 1)
                b.ToolTip = u"Move left" if delta < 0 else u"Move right"
                b.Click += self._move_handler(it, delta)
                C.Grid.SetRow(b, row)
                C.Grid.SetColumn(b, 2 + col)
                g.Children.Add(b)
        self._render_preview()

    def _render_swatches(self):
        w = self.w
        C = w["C"]
        self.swatches.Children.Clear()
        p = self.design.panel
        if p is None:
            return
        for name, hexc in engine.PALETTE:
            b = C.Button()
            b.Width = b.Height = 24
            b.MinWidth = 0
            b.Padding = w["Thickness"](0)
            b.Margin = w["Thickness"](0, 0, 5, 0)
            b.Background = brush(w, hexc)
            chosen = (p.color or u"").upper() == hexc.upper()
            b.BorderBrush = brush(w, "#111827" if chosen else "#CBD5E1")
            b.BorderThickness = w["Thickness"](3 if chosen else 1)
            b.ToolTip = name + (u"  (current)" if chosen else u"")
            b.Click += self._color_handler(hexc)
            self.swatches.Children.Add(b)
        custom = p.color and p.color.upper() not in \
            [h.upper() for _, h in engine.PALETTE]
        if custom:
            b = C.Button()
            b.Width = b.Height = 24
            b.MinWidth = 0
            b.Margin = w["Thickness"](0, 0, 5, 0)
            b.Background = brush(w, p.color)
            b.BorderBrush = brush(w, "#111827")
            b.BorderThickness = w["Thickness"](3)
            b.ToolTip = u"Your colour %s (current)" % p.color
            self.swatches.Children.Add(b)
        for text, handler in ((u"Custom\u2026", self._custom_color),
                              (u"None", self._color_handler(None))):
            b = C.Button()
            b.Content = text
            b.MinWidth = 0
            b.Padding = w["Thickness"](8, 2, 8, 2)
            b.Margin = w["Thickness"](4, 0, 0, 0)
            b.Click += handler
            self.swatches.Children.Add(b)

    def _color_handler(self, hexc):
        def handler(sender, args):
            self.design.set_color(self.design.panel, hexc)
            self._after_color()
        return handler

    def _custom_color(self, sender, args):
        p = self.design.panel
        picked = pick_custom_color(p.color)
        if picked:
            self.design.set_color(p, picked)
            self._after_color()

    def _after_color(self):
        self._render_swatches()
        self._render_preview()
        self._refresh_panel_row()

    def _auto_colors(self, sender, args):
        self.design.auto_colors()
        self._fill_panels()

    def _mode_handler(self, item, opts, combo):
        def handler(sender, args):
            if combo.SelectedIndex >= 0:
                self.design.set_mode(item, opts[combo.SelectedIndex])
                self._render_preview()
        return handler

    def _move_handler(self, item, delta):
        def handler(sender, args):
            if self.design.move(item, delta):
                self._render()
        return handler

    # ------------------------------------------------------------ preview
    def _render_preview(self):
        w = self.w
        C = w["C"]
        self.preview.Children.Clear()
        p = self.design.panel
        if p is None:
            return
        self.preview_strip.Background = brush(w, p.color or "#E2E8F0")
        self.preview_strip_text.Text = p.label
        self.preview_strip_text.Foreground = brush(
            w, engine.text_color_for(p.color))
        for col in engine.preview(p):
            card = C.Border()
            card.Background = brush(w, "#FFFFFF")
            card.BorderBrush = brush(w, "#CBD5E1")
            card.BorderThickness = w["Thickness"](1)
            card.CornerRadius = w["CornerRadius"](4)
            card.Margin = w["Thickness"](0, 0, 6, 6)
            card.Padding = w["Thickness"](8, 4, 8, 4)
            sp = C.StackPanel()
            if len(col) == 1:
                icon = C.TextBlock()
                icon.Text = u"▣"
                icon.FontSize = 20
                icon.HorizontalAlignment = w["HA"].Center
                icon.Foreground = brush(w, "#2563EB")
                sp.Children.Add(icon)
                t = C.TextBlock()
                t.Text = col[0]
                t.HorizontalAlignment = w["HA"].Center
                t.MaxWidth = 90
                t.TextWrapping = w["TextWrapping"].Wrap
                t.TextAlignment = w["TextAlignment"].Center
                sp.Children.Add(t)
            else:
                for name in col:
                    t = C.TextBlock()
                    t.Text = u"▪  " + name
                    t.FontSize = 11
                    sp.Children.Add(t)
            card.Child = sp
            self.preview.Children.Add(card)

    # ------------------------------------------------------------ actions
    def _suggest(self, sender, args):
        self.design.suggest_all()
        self._fill_panels()

    def _reset(self, sender, args):
        self.design.reset()
        self._fill_panels()

    def _open_backups(self, sender, args):
        if not os.path.isdir(BACKUPS):
            os.makedirs(BACKUPS)
        os.startfile(BACKUPS)

    def _undo(self, sender, args):
        ctx = self.design.ctx
        entries = engine.undo_entries(BACKUPS, ctx)
        if not entries:
            forms.alert(u"Nothing to undo - this extension hasn't been changed "
                        u"by the designer from this folder on this PC.",
                        title=u"Tab Designer")
            return
        last = entries[-1]
        if not forms.alert(
                u"Put the extension back as it was before the last Apply "
                u"(%s)?\n\nAnything changed in the extension since then is "
                u"replaced too - a copy of the current state is saved to the "
                u"backups folder first." % last["time"],
                yes=True, no=True, title=u"Tab Designer"):
            return
        try:
            restored, safety = engine.undo_last(BACKUPS, ctx)
        except engine.DesignerError as ex:
            forms.alert(u"%s" % ex, title=u"Tab Designer")
            return
        try:   # new internal panel names so the refresh rebuilds them
            engine.rekey_extension(os.path.join(ctx.root, restored))
        except Exception:
            pass
        self.do_reload = True
        forms.alert(u"Restored %s.\npyRevit will now refresh." % restored,
                    title=u"Tab Designer")
        self.Close()

    def _apply(self, sender, args):
        ctx = self.design.ctx
        name = (self.tab_name.Text or u"").strip()
        problem = engine.check_name(name)
        if problem:
            forms.alert(problem, title=u"Tab Designer")
            return
        rename_ext = bool(self.rename_ext.IsChecked) and \
            bool(self.rename_ext.IsEnabled)
        lines = [u"A backup of the whole extension is made first."]
        for p in self.design.panels:
            cols = engine.preview(p)
            lines.append(u"• %s: %d column(s)" % (p.label, len(cols)))
        if name != ctx.tab_name:
            lines.append(u"• Tab %s → %s" % (ctx.tab_name, name))
        if rename_ext:
            lines.append(u"• Folder %s → %s.extension"
                         % (os.path.basename(ctx.ext_dir), name))
        if not forms.alert(u"Apply this design?\n\n" + u"\n".join(lines),
                           yes=True, no=True, title=u"Tab Designer"):
            return
        try:
            res = engine.apply_design(ctx, self.design.panels, name,
                                      rename_ext, bool(self.opt_fix.IsChecked),
                                      BACKUPS, MORE_ICON, MORE_ICON_DARK)
        except engine.DesignerError as ex:
            forms.alert(u"%s" % ex, title=u"Tab Designer")
            self.design.reset()
            self._fill_panels()
            return
        except Exception as ex:
            forms.alert(u"Something went wrong: %s\n\nYour backup: %s\nUse "
                        u"'Undo last apply' to restore it." % (ex, BACKUPS),
                        title=u"Tab Designer")
            return
        msg = [u"Done."] + [u"• " + n for n in res.notes]
        for old, new in res.renamed:
            msg.append(u"• Renamed %s → %s" % (old, new))
        if res.name_refs and not res.fixed_files:
            msg.append(u"\n%d line(s) in your files still mention the old "
                       u"folder names (e.g. %s). Tick 'Also update old folder "
                       u"names' next time to fix them."
                       % (len(res.name_refs),
                          os.path.basename(res.name_refs[0][0])))
        elif res.fixed_files:
            msg.append(u"• Updated old folder names in %d file(s)."
                       % res.fixed_files)
        if res.renamed:
            msg.append(u"\nRevit keyboard shortcuts set on these buttons "
                       u"need assigning again.")
        refresh = bool(self.opt_refresh.IsChecked)
        msg.append(u"\npyRevit will now refresh." if refresh else
                   u"\nRefresh pyRevit (pyRevit tab > Reload) to see it.")
        forms.alert(u"\n".join(msg), title=u"Tab Designer")
        self.do_reload = refresh
        self.Close()


def main():
    try:
        ctx = engine.find_context(__file__)
    except engine.DesignerError as ex:
        forms.alert(u"%s" % ex, title=u"Tab Designer", exitscript=True)
    design = engine.Design(ctx)
    win = DesignerWindow(design)
    win.ShowDialog()
    if win.do_reload:
        from pyrevit.loader import sessionmgr
        sessionmgr.reload_pyrevit()


if __name__ == "__main__":
    main()
