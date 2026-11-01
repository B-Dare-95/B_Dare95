# -*- coding: utf-8 -*-
"""DLC Export Sheets - progress window.

A list with one row per file (sheet, format, file name, live status, time)
and a total progress bar with percentage, counts, elapsed and remaining time.
Cancel stops after the current Revit export call. When the run ends the
window becomes the results view (Open folder / Close).
"""
import io
import os
import tempfile
import time

from pyrevit import forms

from System import Action
from System.Windows.Threading import DispatcherPriority

import dlc_export_core as core

XAML = u"""<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="DLC Export Sheets - Progress" Width="980" Height="620" MinWidth="720" MinHeight="420"
        WindowStartupLocation="CenterScreen" ShowInTaskbar="True" ResizeMode="CanResize"
        FontSize="12" Background="#F7F7F8">
  <DockPanel Margin="12">
    <StackPanel DockPanel.Dock="Top">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <StackPanel>
          <TextBlock x:Name="lblHeadline" FontSize="16" FontWeight="SemiBold" Text="Preparing export..."/>
          <TextBlock x:Name="lblCurrent" Margin="0,4,0,0" Foreground="#444" TextTrimming="CharacterEllipsis"/>
        </StackPanel>
        <TextBlock x:Name="lblPercent" Grid.Column="1" FontSize="28" FontWeight="Bold"
                   VerticalAlignment="Center" Foreground="#1F5FAD" Text="0 %"/>
      </Grid>
      <ProgressBar x:Name="pbTotal" Height="20" Margin="0,8,0,4" Minimum="0" Maximum="100" Value="0"/>
      <Grid Margin="0,0,0,8">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <TextBlock x:Name="lblCounts" Foreground="#333"/>
        <TextBlock x:Name="lblTimes" Grid.Column="1" Foreground="#333"/>
      </Grid>
    </StackPanel>
    <Grid DockPanel.Dock="Bottom" Margin="0,8,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock x:Name="lblNotes" TextWrapping="Wrap" Foreground="#7A4B00" VerticalAlignment="Center"/>
      <StackPanel Grid.Column="1" Orientation="Horizontal">
        <Button x:Name="btnOpenFolder" Content="Open folder" Padding="12,4" Margin="0,0,6,0" IsEnabled="False"/>
        <Button x:Name="btnCancel" Content="Cancel" Padding="12,4" Margin="0,0,6,0" MinWidth="90"/>
        <Button x:Name="btnClose" Content="Close" Padding="12,4" MinWidth="90" IsEnabled="False"/>
      </StackPanel>
    </Grid>
    <DataGrid x:Name="dgJobs" AutoGenerateColumns="False" IsReadOnly="True" CanUserAddRows="False"
              HeadersVisibility="Column" GridLinesVisibility="Horizontal" RowHeight="22"
              Background="White" SelectionMode="Extended" EnableRowVirtualization="True">
      <DataGrid.RowStyle>
        <Style TargetType="DataGridRow">
          <Setter Property="ToolTip" Value="{Binding Message}"/>
          <Style.Triggers>
            <DataTrigger Binding="{Binding Status}" Value="Exporting...">
              <Setter Property="Background" Value="#E8F0FC"/>
              <Setter Property="FontWeight" Value="SemiBold"/>
            </DataTrigger>
            <DataTrigger Binding="{Binding Status}" Value="Done">
              <Setter Property="Foreground" Value="#1E7B34"/>
            </DataTrigger>
            <DataTrigger Binding="{Binding Status}" Value="Failed">
              <Setter Property="Foreground" Value="#B3261E"/>
              <Setter Property="Background" Value="#FCEBEA"/>
            </DataTrigger>
            <DataTrigger Binding="{Binding Status}" Value="Skipped">
              <Setter Property="Foreground" Value="#777777"/>
            </DataTrigger>
            <DataTrigger Binding="{Binding Status}" Value="Cancelled">
              <Setter Property="Foreground" Value="#777777"/>
            </DataTrigger>
          </Style.Triggers>
        </Style>
      </DataGrid.RowStyle>
      <DataGrid.Columns>
        <DataGridTextColumn Header="#" Binding="{Binding Index}" Width="40"/>
        <DataGridTextColumn Header="Number" Binding="{Binding Number}" Width="100"/>
        <DataGridTextColumn Header="Sheet / View" Binding="{Binding Title}" Width="2*"/>
        <DataGridTextColumn Header="Format" Binding="{Binding Format}" Width="80"/>
        <DataGridTextColumn Header="File name" Binding="{Binding FileName}" Width="3*"/>
        <DataGridTextColumn Header="Status" Binding="{Binding Status}" Width="95"/>
        <DataGridTextColumn Header="Time" Binding="{Binding Time}" Width="60"/>
        <DataGridTextColumn Header="Details" Binding="{Binding Message}" Width="2*"/>
      </DataGrid.Columns>
    </DataGrid>
  </DockPanel>
</Window>
"""

STATUS_TEXT = {
    "pending": u"Waiting",
    "running": u"Exporting...",
    "ok": u"Done",
    "failed": u"Failed",
    "skipped": u"Skipped",
    "cancelled": u"Cancelled",
}
FORMAT_TEXT = {"pdf": u"PDF", "pdf_combined": u"PDF (set)", "dwg": u"DWG"}
FINISHED = ("ok", "failed", "skipped", "cancelled")


def fmt_duration(seconds):
    seconds = int(max(0, round(seconds or 0)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return u"%d:%02d:%02d" % (h, m, s)
    return u"%02d:%02d" % (m, s)


class JobRow(object):
    def __init__(self, index, job):
        self.job = job
        self.Index = index
        self.Number = job.number
        self.Title = job.title or job.label
        self.Format = FORMAT_TEXT.get(job.fmt, job.fmt.upper())
        self.FileName = job.name + job.ext
        self.Status = u""
        self.Time = u""
        self.Message = u""
        self.refresh()

    def refresh(self):
        j = self.job
        self.Status = STATUS_TEXT.get(j.status, j.status)
        self.FileName = j.name + j.ext
        self.Time = u"%.1fs" % j.seconds if j.seconds is not None else u""
        msg = j.message or u" ".join(j.warnings)
        if j.status == "ok" and not msg:
            msg = j.path
        self.Message = msg


class ProgressWindow(forms.WPFWindow):
    """Implements the reporter interface used by dlc_export_revit.run_jobs."""

    def __init__(self, clock=None):
        try:
            forms.WPFWindow.__init__(self, XAML, literal_string=True)
        except Exception:
            path = os.path.join(tempfile.gettempdir(), "dlc_export_progress.xaml")
            with io.open(path, "w", encoding="utf-8") as fh:
                fh.write(XAML)
            forms.WPFWindow.__init__(self, path)
        self._clock = clock or time.time
        self._cancel = False
        self._running = False
        self._t0 = None
        self._t_end = None
        self._last_pump = 0.0
        self.rows = []
        self._row_of = {}
        self.root_folder = None
        self.notes = []
        self.btnCancel.Click += self.on_cancel
        self.btnClose.Click += self.on_close
        self.btnOpenFolder.Click += self.on_open_folder
        self.Closing += self.on_closing

    # ------------------------------------------------------------ reporter API
    def begin(self, jobs):
        self.rows = [JobRow(i + 1, j) for i, j in enumerate(jobs)]
        self._row_of = dict((id(r.job), r) for r in self.rows)
        self.dgJobs.ItemsSource = self.rows
        self._t0 = self._clock()
        self._running = True
        self._refresh_header(None)
        self.pump(force=True)

    def update(self, job):
        row = self._row_of.get(id(job))
        if row is None:
            return
        row.refresh()
        if job.status == "running":
            try:
                self.dgJobs.ScrollIntoView(row)
            except Exception:
                pass
        self._refresh_header(job)
        self.dgJobs.Items.Refresh()
        self.pump()

    def cancelled(self):
        self.pump(force=True)
        return self._cancel

    def finish(self, jobs):
        self._running = False
        self._t_end = self._clock()
        for r in self.rows:
            r.refresh()
        self.dgJobs.Items.Refresh()
        self._refresh_header(None, final=True)
        self.btnCancel.Visibility = self._collapsed()
        self.btnClose.IsEnabled = True
        self.btnOpenFolder.IsEnabled = bool(self.root_folder and os.path.isdir(self.root_folder))
        self.pump(force=True)

    # ------------------------------------------------------------ display
    @staticmethod
    def _collapsed():
        try:
            from System.Windows import Visibility
            return Visibility.Collapsed
        except Exception:
            return "Collapsed"

    def counts(self):
        c = {"total": len(self.rows), "ok": 0, "failed": 0, "skipped": 0, "cancelled": 0,
             "running": 0, "pending": 0}
        for r in self.rows:
            c[r.job.status] = c.get(r.job.status, 0) + 1
        c["finished"] = c["ok"] + c["failed"] + c["skipped"] + c["cancelled"]
        return c

    def percent(self):
        c = self.counts()
        if not c["total"]:
            return 100
        return int(100.0 * c["finished"] / c["total"])

    def _refresh_header(self, job, final=False):
        c = self.counts()
        pct = 100 if final and c["cancelled"] == 0 else self.percent()
        self.pbTotal.Value = pct
        self.lblPercent.Text = u"%d %%" % pct
        now = self._t_end if final and self._t_end else self._clock()
        elapsed = (now - self._t0) if self._t0 is not None else 0
        exported = c["ok"] + c["failed"]
        remaining_jobs = c["pending"] + c["running"]
        if final:
            if c["cancelled"]:
                self.lblHeadline.Text = u"Cancelled - %d of %d files exported" % (c["ok"], c["total"])
            elif c["failed"]:
                self.lblHeadline.Text = u"Finished with %d failed file(s)" % c["failed"]
            else:
                self.lblHeadline.Text = u"Export complete - %d file(s)" % c["ok"]
            self.lblCurrent.Text = (u"Saved to: %s" % self.root_folder) if self.root_folder else u""
            self.lblTimes.Text = u"Total time %s" % fmt_duration(elapsed)
        else:
            self.lblHeadline.Text = u"Exporting %d of %d files" % (min(c["finished"] + 1, c["total"]),
                                                                    c["total"])
            if job is not None and job.status == "running":
                self.lblCurrent.Text = u"Current: %s  (%s)" % (job.label, FORMAT_TEXT.get(job.fmt, job.fmt))
            if exported and remaining_jobs:
                eta = elapsed / float(c["finished"] or 1) * remaining_jobs
                self.lblTimes.Text = u"Elapsed %s   |   Remaining ~%s" % (fmt_duration(elapsed),
                                                                        fmt_duration(eta))
            else:
                self.lblTimes.Text = u"Elapsed %s" % fmt_duration(elapsed)
        self.lblCounts.Text = u"Done %d   |   Failed %d   |   Skipped %d   |   Waiting %d" % (
            c["ok"], c["failed"], c["skipped"], c["pending"] + c["running"])
        if self.notes:
            self.lblNotes.Text = u"  ".join(self.notes[:3])

    def pump(self, force=False):
        """Let WPF repaint and process the Cancel click while Revit is busy."""
        now = self._clock()
        if not force and now - self._last_pump < 0.05:
            return
        self._last_pump = now
        try:
            self.Dispatcher.Invoke(Action(lambda: None), DispatcherPriority.Background)
        except Exception:
            pass

    # ------------------------------------------------------------ events
    def on_cancel(self, sender, args):
        if self._running:
            self._cancel = True
            self.btnCancel.IsEnabled = False
            self.btnCancel.Content = u"Stopping..."
            self.lblCurrent.Text = u"Stopping after the current Revit export call..."

    def on_close(self, sender, args):
        self.Close()

    def on_closing(self, sender, args):
        if self._running:                 # closing mid-run = cancel, keep window
            self._cancel = True
            try:
                args.Cancel = True
            except Exception:
                pass
            self.on_cancel(sender, args)

    def on_open_folder(self, sender, args):
        open_folder(self.root_folder)


def open_folder(folder):
    if not folder:
        return
    try:
        os.startfile(folder)
        return
    except Exception:
        pass
    try:
        from System.Diagnostics import Process
        Process.Start("explorer.exe", u'"%s"' % folder)
    except Exception:
        pass


def summary_lines(jobs, log):
    """Plain-text summary (used for the output window when needed)."""
    c = core.summarize(jobs)
    lines = [u"Exported %d, failed %d, skipped %d, cancelled %d." % (
        c["ok"], c["failed"], c["skipped"], c["cancelled"])]
    for j in jobs:
        if j.status == "failed":
            lines.append(u"FAILED %s (%s): %s" % (j.label, j.fmt, j.message))
    lines.extend(log)
    return lines
