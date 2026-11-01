# -*- coding: utf-8 -*-
"""Calculate GLA and GFA for rooms.

GLA (Gross Leasable Area): interior walls to centreline, exterior walls to
the inner finish face. Only rooms with DLC_Is_Leasable = Yes get a GLA.
GFA (Gross Floor Area): interior walls to centreline, exterior walls to the
outer face. Results go to DLC_GLA / DLC_GFA and an optional Excel report.
"""
__title__ = 'Room\nAreas'
__author__ = 'DLC'

import os
import sys
import datetime

# --------------------------------------------------------------------------
# SETTINGS - firm-level options. Change here, not in the code below.
# --------------------------------------------------------------------------
SETTINGS = {
    # room parameters (fixed GUIDs = identical in every building model)
    'PARAM_GLA': 'DLC_GLA',
    'GUID_GLA': '4d5b399a-7098-4393-b411-ad81e17efd4e',
    'PARAM_GFA': 'DLC_GFA',
    'GUID_GFA': '10e9fae3-520b-4010-b28a-3ced820f1d8e',
    'PARAM_LEASABLE': 'DLC_Is_Leasable',
    'GUID_LEASABLE': '025742f8-9d0f-4420-b8e4-ed2170b70a25',
    'SHARED_PARAM_GROUP': 'DLC',

    # wall type Functions treated as EXTERIOR
    'EXTERIOR_FUNCTIONS': ('EXTERIOR', 'FOUNDATION', 'RETAINING'),

    # columns in a wall line are bridged (not deducted)
    'BRIDGE_COLUMNS': True,
    # free-standing columns inside a room are not deducted
    'DEDUCT_FREESTANDING_COLUMNS': False,

    # curtain walls report 0 thickness in Revit; depth used for GFA (mm)
    'CURTAIN_WALL_DEPTH_MM': 0.0,

    # how far beyond the wall face to look for a room behind it (mm)
    'PROBE_GAP_MM': 200.0,

    # report
    'DECIMALS': 2,
    'REPORT_NAME': '{model}_GLA-GFA_{date}.xlsx',
}

# --------------------------------------------------------------------------
# find our lib folder wherever the extension has been copied to
# --------------------------------------------------------------------------
def _add_lib():
    here = os.path.dirname(os.path.abspath(__file__))
    d = here
    for _ in range(6):
        cand = os.path.join(d, 'lib')
        if os.path.isdir(os.path.join(cand, 'dlc_roomarea')):
            if cand not in sys.path:
                sys.path.insert(0, cand)
            return
        d = os.path.dirname(d)


_add_lib()

import clr  # noqa: E402
clr.AddReference('System.Data')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
import System  # noqa: E402
from System.Data import DataTable  # noqa: E402
from System.Windows.Input import Mouse, Cursors  # noqa: E402

from pyrevit import revit, forms, script  # noqa: E402
from Autodesk.Revit import DB  # noqa: E402

from dlc_roomarea import engine, revit_io, report, xlsx  # noqa: E402

doc = revit.doc
uidoc = revit.uidoc
app = doc.Application
MM = 1.0 / 304.8


def engine_settings():
    return {
        'EXTERIOR_FUNCTIONS': tuple(SETTINGS['EXTERIOR_FUNCTIONS']),
        'BRIDGE_COLUMNS': SETTINGS['BRIDGE_COLUMNS'],
        'DEDUCT_FREESTANDING_COLUMNS': SETTINGS['DEDUCT_FREESTANDING_COLUMNS'],
        'CURTAIN_WALL_DEPTH': SETTINGS['CURTAIN_WALL_DEPTH_MM'] * MM,
        'PROBE_GAP': SETTINGS['PROBE_GAP_MM'] * MM,
    }


def param_specs():
    return [
        (SETTINGS['PARAM_GLA'], SETTINGS['GUID_GLA'], 'AREA',
         'Gross Leasable Area - interior walls to centreline, exterior '
         'walls to inner face. Written by DLC Room Areas.'),
        (SETTINGS['PARAM_GFA'], SETTINGS['GUID_GFA'], 'AREA',
         'Gross Floor Area - interior walls to centreline, exterior walls '
         'to outer face. Written by DLC Room Areas.'),
        (SETTINGS['PARAM_LEASABLE'], SETTINGS['GUID_LEASABLE'], 'YESNO',
         'Tick for rooms that count toward GLA.'),
    ]


# --------------------------------------------------------------------------
# measuring
# --------------------------------------------------------------------------
def measure_rooms(rooms, blank_as_leasable):
    st = engine_settings()
    opts = revit_io.boundary_options()
    results = []
    for room in rooms:
        r = {'room': room,
             'number': revit_io.room_number(room),
             'name': revit_io.room_name(room),
             'level': revit_io.room_level_name(doc, room),
             'level_elev': 0.0,
             'revit_area': revit_io.room_area_ft2(room)}
        try:
            r['level_elev'] = doc.GetElement(room.LevelId).Elevation
        except Exception:
            pass
        try:
            loops = revit_io.extract_loops(doc, room, st, opts)
            if not loops:
                r['error'] = engine.FLAG_TEXT['NO_BOUNDARY']
                results.append(r)
                continue
            m = engine.compute_room(loops, st)
            val = revit_io.read_yes_no(room, SETTINGS['PARAM_LEASABLE'])
            leasable, lflags = engine.resolve_leasable(val, blank_as_leasable)
            r['base'] = m['base']
            r['gfa'] = m['gfa']
            r['gla_measured'] = m['gla']
            r['gla'] = m['gla'] if leasable else 0.0
            r['leasable'] = leasable
            r['leasable_blank'] = val is None
            r['flags'] = m['flags'] + lflags
            r['walls'] = m['walls']
        except Exception as ex:
            r['error'] = 'Could not measure this room (%s). Check it is ' \
                         'properly enclosed.' % ex
        results.append(r)
    return results


def write_results(results):
    """Create parameters if needed and write values. Returns summary dict."""
    missing, problems = revit_io.check_parameters(doc, param_specs())
    if problems:
        return {'fatal': '\n\n'.join(problems)}
    summary = {'written': 0, 'owned': 0, 'failed': 0, 'created': []}
    t = DB.Transaction(doc, 'DLC Room Areas - write GLA/GFA')
    t.Start()
    try:
        if missing:
            summary['created'] = revit_io.ensure_parameters(
                doc, app, param_specs(), SETTINGS['SHARED_PARAM_GROUP'])
            doc.Regenerate()
        for r in results:
            if r.get('error'):
                continue
            room = r['room']
            owner = revit_io.owned_by_other(doc, room)
            if owner:
                r['write_error'] = 'Room is borrowed by %s - ask them to ' \
                                   'sync, then run again.' % owner
                summary['owned'] += 1
                continue
            sub = DB.SubTransaction(doc)
            sub.Start()
            try:
                revit_io.write_area(room, SETTINGS['PARAM_GLA'], r['gla'])
                revit_io.write_area(room, SETTINGS['PARAM_GFA'], r['gfa'])
                sub.Commit()
                summary['written'] += 1
            except Exception as ex:
                sub.RollBack()
                r['write_error'] = str(ex)
                summary['failed'] += 1
        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        return {'fatal': 'Nothing was written - the change was rolled '
                         'back.\n\nReason: %s' % ex}
    return summary


def export_results(results):
    model = os.path.splitext(doc.Title or 'Model')[0]
    name = SETTINGS['REPORT_NAME'].format(
        model=model, date=datetime.date.today().strftime('%Y%m%d'))
    path = forms.save_file(file_ext='xlsx', default_name=name)
    if not path:
        return None
    xlsx.write_workbook(path, report.build_sheets(results,
                                                  SETTINGS['DECIMALS']))
    return path


# --------------------------------------------------------------------------
# window
# --------------------------------------------------------------------------
XAML = u'''<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="DLC Room Areas - GLA / GFA" Width="980" Height="640"
        MinWidth="760" MinHeight="460"
        WindowStartupLocation="CenterScreen" ShowInTaskbar="False"
        FontFamily="Segoe UI" FontSize="12">
  <Grid Margin="12">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <TextBlock Grid.Row="0" TextWrapping="Wrap" Foreground="#555" Margin="0,0,0,10"
      Text="GLA: interior walls to centreline, exterior walls to inner face (leasable rooms only).   GFA: interior walls to centreline, exterior walls to outer face."/>
    <Grid Grid.Row="1" Margin="0,0,0,10">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <GroupBox Grid.Column="0" Header="Rooms" Margin="0,0,8,0" Padding="6">
        <StackPanel>
          <RadioButton x:Name="scope_all" Content="All placed rooms in the model" Margin="0,2"/>
          <RadioButton x:Name="scope_level" Content="Rooms on the active view's level" Margin="0,2"/>
          <RadioButton x:Name="scope_sel" Content="Selected rooms" Margin="0,2"/>
        </StackPanel>
      </GroupBox>
      <GroupBox Grid.Column="1" Header="Options" Margin="0,0,8,0" Padding="6">
        <StackPanel>
          <CheckBox x:Name="chk_write" Content="Write DLC_GLA / DLC_GFA to rooms" Margin="0,2"/>
          <CheckBox x:Name="chk_export" Content="Export Excel report" Margin="0,2"/>
          <CheckBox x:Name="chk_blank" Content="Count rooms with blank DLC_Is_Leasable as leasable" Margin="0,2"/>
        </StackPanel>
      </GroupBox>
      <Button Grid.Column="2" x:Name="btn_preview" Content="Preview" Width="110" Height="34" VerticalAlignment="Bottom"/>
    </Grid>
    <DataGrid Grid.Row="2" x:Name="grid" IsReadOnly="True" AutoGenerateColumns="True"
              CanUserAddRows="False" HeadersVisibility="Column"
              AlternatingRowBackground="#F4F6F8" GridLinesVisibility="Horizontal"/>
    <TextBlock Grid.Row="3" x:Name="txt_summary" Margin="0,10,0,0" FontWeight="SemiBold"
               TextWrapping="Wrap" Text="Choose the rooms and press Preview."/>
    <StackPanel Grid.Row="4" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
      <Button x:Name="btn_apply" Content="Apply" Width="110" Height="30" Margin="0,0,8,0" IsEnabled="False"/>
      <Button x:Name="btn_close" Content="Close" Width="90" Height="30" IsCancel="True"/>
    </StackPanel>
  </Grid>
</Window>'''


def _load_window(cls):
    try:
        return cls(XAML, literal_string=True)
    except TypeError:
        # older pyRevit builds only accept a file path
        import tempfile
        p = os.path.join(tempfile.gettempdir(), 'DLC_RoomAreas.xaml')
        with open(p, 'wb') as f:
            f.write(XAML.encode('utf-8'))
        return cls(p)


class RoomAreasWindow(forms.WPFWindow):
    def __init__(self, xaml, literal_string=False):
        forms.WPFWindow.__init__(self, xaml, literal_string=literal_string)
        self.cfg = script.get_config()
        scope = self.cfg.get_option('scope', 'ALL')
        {'ALL': self.scope_all, 'LEVEL': self.scope_level,
         'SELECTION': self.scope_sel}.get(scope, self.scope_all).IsChecked = True
        if scope == 'ALL' and uidoc.Selection.GetElementIds().Count:
            self.scope_sel.IsChecked = True
        self.chk_write.IsChecked = self.cfg.get_option('write', True)
        self.chk_export.IsChecked = self.cfg.get_option('export', True)
        self.chk_blank.IsChecked = self.cfg.get_option('blank_leasable', False)
        self.results = None
        self.outcome = None
        self.btn_preview.Click += self.on_preview
        self.btn_apply.Click += self.on_apply
        self.btn_close.Click += self.on_close
        for c in (self.scope_all, self.scope_level, self.scope_sel,
                  self.chk_blank):
            c.Checked += self.on_changed
            c.Unchecked += self.on_changed

    # -- helpers ------------------------------------------------------------
    def scope(self):
        if self.scope_level.IsChecked:
            return 'LEVEL'
        if self.scope_sel.IsChecked:
            return 'SELECTION'
        return 'ALL'

    def save_cfg(self):
        self.cfg.scope = self.scope()
        self.cfg.write = bool(self.chk_write.IsChecked)
        self.cfg.export = bool(self.chk_export.IsChecked)
        self.cfg.blank_leasable = bool(self.chk_blank.IsChecked)
        script.save_config()

    def on_changed(self, sender, args):
        # results no longer match the options - force a new preview
        if self.results is not None:
            self.results = None
            self.btn_apply.IsEnabled = False
            self.txt_summary.Text = 'Options changed - press Preview again.'

    def fill_grid(self, results):
        dec = SETTINGS['DECIMALS']
        tbl = DataTable()
        cols = [('Level', System.String), ('Number', System.String),
                ('Name', System.String), ('Leasable', System.String),
                ('GLA m2', System.Double), ('GFA m2', System.Double),
                ('Revit Area m2', System.Double), ('QA', System.String)]
        for name, typ in cols:
            tbl.Columns.Add(name, clr.GetClrType(typ))
        for r in report.sort_results(results):
            row = tbl.NewRow()
            row['Level'] = r.get('level', '')
            row['Number'] = r.get('number', '')
            row['Name'] = r.get('name', '')
            row['Revit Area m2'] = report.m2(r.get('revit_area', 0.0), dec)
            if r.get('error'):
                row['Leasable'] = ''
            else:
                row['Leasable'] = 'Yes' if r['leasable'] else (
                    'No (blank)' if r.get('leasable_blank') else 'No')
                row['GLA m2'] = report.m2(r['gla'], dec)
                row['GFA m2'] = report.m2(r['gfa'], dec)
            row['QA'] = '; '.join(i for i, _ in report.qa_items(r))
            tbl.Rows.Add(row)
        self.grid.ItemsSource = tbl.DefaultView

    # -- events ---------------------------------------------------------------
    def on_preview(self, sender, args):
        rooms, msg = revit_io.collect_rooms(doc, uidoc, self.scope())
        if not rooms:
            self.txt_summary.Text = msg or 'No placed rooms found.'
            self.btn_apply.IsEnabled = False
            return
        Mouse.OverrideCursor = Cursors.Wait
        try:
            self.results = measure_rooms(rooms,
                                         bool(self.chk_blank.IsChecked))
        finally:
            Mouse.OverrideCursor = None
        self.fill_grid(self.results)
        t = report.totals(self.results)
        dec = SETTINGS['DECIMALS']
        blank = len([r for r in self.results if r.get('leasable_blank')])
        errors = len([r for r in self.results if r.get('error')])
        parts = ['%d rooms   |   GLA %s m2 (%d leasable)   |   GFA %s m2'
                 % (t['rooms'], '{:,.{}f}'.format(report.m2(t['gla'], dec), dec),
                    t['leasable'],
                    '{:,.{}f}'.format(report.m2(t['gfa'], dec), dec))]
        if errors:
            parts.append('%d room(s) could not be measured.' % errors)
        if blank:
            parts.append('%d room(s) have no DLC_Is_Leasable value and are '
                         'counted as %s.' % (blank, 'leasable'
                                             if self.chk_blank.IsChecked
                                             else 'NOT leasable'))
        if msg:
            parts.append(msg)
        self.txt_summary.Text = '\n'.join(parts)
        self.btn_apply.IsEnabled = True

    def on_apply(self, sender, args):
        if not self.results:
            return
        if not (self.chk_write.IsChecked or self.chk_export.IsChecked):
            forms.alert('Tick "Write" and/or "Export" first.', title='DLC')
            return
        self.save_cfg()
        self.outcome = {'write': None, 'export': None}
        if self.chk_write.IsChecked:
            self.outcome['write'] = write_results(self.results)
            if self.outcome['write'].get('fatal'):
                forms.alert(self.outcome['write']['fatal'],
                            title='DLC Room Areas - nothing written')
                self.outcome = None
                return
        if self.chk_export.IsChecked:
            try:
                self.outcome['export'] = export_results(self.results)
            except Exception as ex:
                forms.alert('The Excel report could not be saved. Is the '
                            'file open in Excel?\n\n%s' % ex, title='DLC')
        self.Close()

    def on_close(self, sender, args):
        self.save_cfg()
        self.Close()


def main():
    if doc.IsFamilyDocument:
        forms.alert('Open a project model - rooms do not exist in families.',
                    title='DLC Room Areas', exitscript=True)
    win = _load_window(RoomAreasWindow)
    win.ShowDialog()
    out = win.outcome
    if not out:
        return
    lines = []
    w = out.get('write')
    if w:
        if w.get('created'):
            lines.append('Parameters added: %s' % ', '.join(w['created']))
        lines.append('%d room(s) updated.' % w['written'])
        if w['owned']:
            lines.append('%d room(s) skipped - borrowed by other users '
                         '(listed in the report).' % w['owned'])
        if w['failed']:
            lines.append('%d room(s) could not be written (see report).'
                         % w['failed'])
    if out.get('export'):
        lines.append('Report saved:\n%s' % out['export'])
    if lines:
        forms.alert('\n'.join(lines), title='DLC Room Areas - done')


if __name__ == '__main__':
    main()
