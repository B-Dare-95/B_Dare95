# -*- coding: utf-8 -*-
"""DLC Export Sheets - dialog (WPF, embedded XAML, pyRevit WPFWindow)."""
import datetime
import io
import os
import tempfile

from pyrevit import forms

from System.Windows import RoutedEventHandler, Visibility
from System.Windows.Controls.Primitives import ButtonBase

import dlc_export_core as core

XAML = u"""<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="DLC Export Sheets - PDF + DWG" Width="1180" Height="780"
        MinWidth="980" MinHeight="620" WindowStartupLocation="CenterScreen"
        ShowInTaskbar="False" ResizeMode="CanResize" FontSize="12" Background="#F7F7F8">
  <Window.Resources>
    <Style TargetType="GroupBox">
      <Setter Property="Margin" Value="0,0,0,8"/>
      <Setter Property="Padding" Value="6"/>
    </Style>
    <Style TargetType="Button">
      <Setter Property="Padding" Value="10,3"/>
      <Setter Property="Margin" Value="0,0,6,0"/>
      <Setter Property="MinWidth" Value="70"/>
    </Style>
    <Style TargetType="CheckBox"><Setter Property="Margin" Value="0,3,12,3"/></Style>
    <Style TargetType="RadioButton"><Setter Property="Margin" Value="0,3,12,3"/></Style>
    <Style TargetType="TextBox"><Setter Property="Padding" Value="3,2"/></Style>
  </Window.Resources>
  <DockPanel Margin="10">
    <Grid DockPanel.Dock="Bottom" Margin="0,8,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock x:Name="lblSummary" VerticalAlignment="Center" FontWeight="SemiBold" TextWrapping="Wrap"/>
      <StackPanel Grid.Column="1" Orientation="Horizontal">
        <Button x:Name="btnExport" Content="Export" IsDefault="True" MinWidth="110" FontWeight="Bold"/>
        <Button x:Name="btnCancel" Content="Cancel" IsCancel="True" Margin="0"/>
      </StackPanel>
    </Grid>
    <TabControl x:Name="tabs">
      <!-- ============ SELECTION ============ -->
      <TabItem Header="1  Selection">
        <DockPanel Margin="6">
          <WrapPanel DockPanel.Dock="Top" Margin="0,0,0,6">
            <RadioButton x:Name="rbSheets" Content="Sheets" GroupName="mode" IsChecked="True"/>
            <RadioButton x:Name="rbViews" Content="Views" GroupName="mode"/>
            <TextBlock Text="Show:" VerticalAlignment="Center" Margin="12,0,4,0"/>
            <ComboBox x:Name="cbFilter" Width="260"/>
            <TextBlock Text="Search:" VerticalAlignment="Center" Margin="12,0,4,0"/>
            <TextBox x:Name="tbSearch" Width="260"/>
          </WrapPanel>
          <WrapPanel DockPanel.Dock="Bottom" Margin="0,6,0,0">
            <Button x:Name="btnCheckAll" Content="Check all shown"/>
            <Button x:Name="btnUncheckAll" Content="Uncheck all shown"/>
            <Button x:Name="btnCheckSel" Content="Check highlighted rows"/>
            <Button x:Name="btnUncheckSel" Content="Uncheck highlighted rows"/>
            <Button x:Name="btnSaveSet" Content="Save checked as set..."/>
            <Button x:Name="btnDeleteSet" Content="Delete saved set"/>
            <TextBlock x:Name="lblCount" VerticalAlignment="Center" Margin="8,0,0,0"/>
          </WrapPanel>
          <DataGrid x:Name="dgItems" AutoGenerateColumns="False" CanUserAddRows="False"
                    CanUserDeleteRows="False" SelectionMode="Extended" HeadersVisibility="Column"
                    GridLinesVisibility="Horizontal" RowHeight="22" Background="White"
                    EnableRowVirtualization="True">
            <DataGrid.Columns>
              <DataGridTemplateColumn Header="Export" Width="58">
                <DataGridTemplateColumn.CellTemplate>
                  <DataTemplate>
                    <CheckBox HorizontalAlignment="Center" Margin="0"
                              IsChecked="{Binding Checked, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"/>
                  </DataTemplate>
                </DataGridTemplateColumn.CellTemplate>
              </DataGridTemplateColumn>
              <DataGridTextColumn Header="Number" Binding="{Binding Number}" IsReadOnly="True" Width="110"/>
              <DataGridTextColumn Header="Name" Binding="{Binding Name}" IsReadOnly="True" Width="2*"/>
              <DataGridTextColumn Header="Revision" Binding="{Binding Revision}" IsReadOnly="True" Width="80"/>
              <DataGridTextColumn Header="Size" Binding="{Binding Size}" IsReadOnly="True" Width="90"/>
              <DataGridTextColumn Header="Orientation" Binding="{Binding Orientation}" IsReadOnly="True" Width="85"/>
              <DataGridTextColumn Header="View Type" Binding="{Binding ViewType}" IsReadOnly="True" Width="110"/>
              <DataGridTextColumn Header="File name" Binding="{Binding FileName}" IsReadOnly="True" Width="3*"/>
            </DataGrid.Columns>
          </DataGrid>
        </DockPanel>
      </TabItem>
      <!-- ============ NAMING ============ -->
      <TabItem Header="2  File Naming">
        <Grid Margin="6">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="*"/>
          </Grid.ColumnDefinitions>
          <Grid.RowDefinitions>
            <RowDefinition Height="*"/>
            <RowDefinition Height="170"/>
          </Grid.RowDefinitions>
          <GroupBox Header="Available parameters (sheet, title block, project information, shared)">
            <DockPanel>
              <TextBox x:Name="tbParamSearch" DockPanel.Dock="Top" Margin="0,0,0,4" ToolTip="Filter parameters"/>
              <ListBox x:Name="lbParams" DisplayMemberPath="Display" SelectionMode="Extended"/>
            </DockPanel>
          </GroupBox>
          <StackPanel Grid.Column="1" VerticalAlignment="Center" Margin="8,0">
            <Button x:Name="btnAddField" Content="Add  &gt;&gt;" Margin="0,0,0,6"/>
            <Button x:Name="btnRemoveField" Content="&lt;&lt;  Remove" Margin="0,0,0,18"/>
            <Button x:Name="btnUp" Content="Move up" Margin="0,0,0,6"/>
            <Button x:Name="btnDown" Content="Move down" Margin="0,0,0,18"/>
            <TextBlock Text="Custom text:"/>
            <TextBox x:Name="tbCustomText" Width="120" Margin="0,2,0,4"/>
            <Button x:Name="btnAddText" Content="Add text" Margin="0"/>
          </StackPanel>
          <GroupBox Grid.Column="2" Header="File name fields (in order)">
            <DockPanel>
              <Grid DockPanel.Dock="Bottom" Margin="0,6,0,0">
                <Grid.ColumnDefinitions>
                  <ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/>
                  <ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <Grid.RowDefinitions>
                  <RowDefinition/><RowDefinition/><RowDefinition/>
                </Grid.RowDefinitions>
                <TextBlock Text="Separator after field:" VerticalAlignment="Center" Margin="0,0,6,0"/>
                <TextBox x:Name="tbSep" Grid.Column="1" Margin="0,2"/>
                <TextBlock Grid.Column="2" Text="Replace illegal characters with:" VerticalAlignment="Center" Margin="8,0,6,0"/>
                <TextBox x:Name="tbReplace" Grid.Column="3" Margin="0,2" MaxLength="3"/>
                <TextBlock Grid.Row="1" Text="Prefix:" VerticalAlignment="Center"/>
                <TextBox x:Name="tbPrefix" Grid.Row="1" Grid.Column="1" Margin="0,2"/>
                <TextBlock Grid.Row="1" Grid.Column="2" Text="Suffix:" VerticalAlignment="Center" Margin="8,0,6,0"/>
                <TextBox x:Name="tbSuffix" Grid.Row="1" Grid.Column="3" Margin="0,2"/>
                <CheckBox x:Name="chkSkipEmpty" Grid.Row="2" Grid.ColumnSpan="4"
                          Content="Skip empty values (and their separator)"/>
              </Grid>
              <ListBox x:Name="lbFields" DisplayMemberPath="Display"/>
            </DockPanel>
          </GroupBox>
          <GroupBox Grid.Row="1" Grid.ColumnSpan="3" Header="Preview (checked items, or first items if none are checked)">
            <ListBox x:Name="lbPreview"/>
          </GroupBox>
        </Grid>
      </TabItem>
      <!-- ============ PDF ============ -->
      <TabItem Header="3  PDF Settings">
        <ScrollViewer VerticalScrollBarVisibility="Auto">
        <Grid Margin="6">
          <Grid.ColumnDefinitions><ColumnDefinition/><ColumnDefinition/></Grid.ColumnDefinitions>
          <StackPanel Margin="0,0,8,0">
            <GroupBox Header="Paper">
              <StackPanel>
                <TextBlock Text="Paper size ('Default' = each sheet's own title block size):"/>
                <ComboBox x:Name="cbPaper" Margin="0,2,0,6"/>
                <TextBlock Text="Orientation:"/>
                <ComboBox x:Name="cbOrient" Margin="0,2,0,0"/>
              </StackPanel>
            </GroupBox>
            <GroupBox Header="Paper placement">
              <StackPanel>
                <RadioButton x:Name="rbCenter" Content="Center" GroupName="place"/>
                <StackPanel Orientation="Horizontal">
                  <RadioButton x:Name="rbOffset" Content="Offset from corner (mm)  X:" GroupName="place"/>
                  <TextBox x:Name="tbOffX" Width="60"/>
                  <TextBlock Text="  Y:" VerticalAlignment="Center"/>
                  <TextBox x:Name="tbOffY" Width="60"/>
                </StackPanel>
              </StackPanel>
            </GroupBox>
            <GroupBox Header="Zoom">
              <StackPanel>
                <RadioButton x:Name="rbFit" Content="Fit to page" GroupName="zoom"/>
                <StackPanel Orientation="Horizontal">
                  <RadioButton x:Name="rbZoom" Content="Zoom %:" GroupName="zoom"/>
                  <TextBox x:Name="tbZoom" Width="60"/>
                </StackPanel>
              </StackPanel>
            </GroupBox>
            <GroupBox Header="Hidden line views">
              <StackPanel Orientation="Horizontal">
                <RadioButton x:Name="rbVector" Content="Vector processing" GroupName="hl"/>
                <RadioButton x:Name="rbRaster" Content="Raster processing" GroupName="hl"/>
              </StackPanel>
            </GroupBox>
            <GroupBox Header="Appearance">
              <Grid>
                <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition/></Grid.ColumnDefinitions>
                <Grid.RowDefinitions><RowDefinition/><RowDefinition/><RowDefinition/></Grid.RowDefinitions>
                <TextBlock Text="Colors:" VerticalAlignment="Center" Margin="0,0,8,0"/>
                <ComboBox x:Name="cbColor" Grid.Column="1" Margin="0,2"/>
                <TextBlock Grid.Row="1" Text="Raster quality:" VerticalAlignment="Center" Margin="0,0,8,0"/>
                <ComboBox x:Name="cbRasterQ" Grid.Row="1" Grid.Column="1" Margin="0,2"/>
                <TextBlock Grid.Row="2" Text="Export quality:" VerticalAlignment="Center" Margin="0,0,8,0"/>
                <ComboBox x:Name="cbDpi" Grid.Row="2" Grid.Column="1" Margin="0,2"/>
              </Grid>
            </GroupBox>
          </StackPanel>
          <StackPanel Grid.Column="1">
            <GroupBox Header="Options">
              <StackPanel>
                <CheckBox x:Name="chkLinksBlue" Content="View links in blue"/>
                <CheckBox x:Name="chkHideRef" Content="Hide reference / work planes"/>
                <CheckBox x:Name="chkHideTags" Content="Hide unreferenced view tags"/>
                <CheckBox x:Name="chkHideScope" Content="Hide scope boxes"/>
                <CheckBox x:Name="chkHideCrop" Content="Hide crop boundaries"/>
                <CheckBox x:Name="chkHalftone" Content="Replace halftone with thin lines"/>
                <CheckBox x:Name="chkMask" Content="Region edges mask coincident lines"/>
              </StackPanel>
            </GroupBox>
            <GroupBox Header="File">
              <StackPanel>
                <RadioButton x:Name="rbSeparate" Content="Separate PDF per sheet/view" GroupName="pdfmode"/>
                <RadioButton x:Name="rbCombined" Content="One combined PDF" GroupName="pdfmode"/>
                <RadioButton x:Name="rbBoth" Content="Both separate files and a combined PDF" GroupName="pdfmode"/>
                <TextBlock Text="Combined file name (tokens allowed, e.g. %ProjectNumber% %YYYY-%mm-%dd):" Margin="0,6,0,2" TextWrapping="Wrap"/>
                <TextBox x:Name="tbCombinedName"/>
                <TextBlock Text="Page order in combined PDF:" Margin="0,6,0,2"/>
                <ComboBox x:Name="cbCombineOrder"/>
              </StackPanel>
            </GroupBox>
          </StackPanel>
        </Grid>
        </ScrollViewer>
      </TabItem>
      <!-- ============ DWG ============ -->
      <TabItem Header="4  DWG Settings">
        <StackPanel Margin="6" MaxWidth="700" HorizontalAlignment="Left">
          <GroupBox Header="Export setup">
            <StackPanel>
              <TextBlock TextWrapping="Wrap" Text="Layers, line weights, units, fonts and coordinates come from the Revit DWG export setup (File &gt; Export &gt; CAD Formats &gt; DWG &gt; Modify export setup)."/>
              <ComboBox x:Name="cbDwgSetup" Margin="0,6,0,0"/>
            </StackPanel>
          </GroupBox>
          <GroupBox Header="Views on sheets and links">
            <StackPanel>
              <RadioButton x:Name="rbMerged" Content="Merged - one self-contained DWG per sheet" GroupName="xref"/>
              <RadioButton x:Name="rbXref" Content="Export views on sheets and links as external references" GroupName="xref"/>
            </StackPanel>
          </GroupBox>
          <GroupBox Header="Clean-up">
            <CheckBox x:Name="chkDeletePcp" Content="Delete the .pcp files Revit writes next to each DWG"/>
          </GroupBox>
        </StackPanel>
      </TabItem>
      <!-- ============ EXPORT ============ -->
      <TabItem Header="5  Export">
        <ScrollViewer VerticalScrollBarVisibility="Auto">
        <StackPanel Margin="6">
          <GroupBox Header="Formats">
            <StackPanel Orientation="Horizontal">
              <CheckBox x:Name="chkPdf" Content="PDF"/>
              <CheckBox x:Name="chkDwg" Content="DWG"/>
            </StackPanel>
          </GroupBox>
          <GroupBox Header="Export location">
            <StackPanel>
              <DockPanel>
                <Button x:Name="btnBrowse" Content="Browse..." DockPanel.Dock="Right" Margin="6,0,0,0"/>
                <TextBox x:Name="tbRoot"/>
              </DockPanel>
              <TextBlock Margin="0,4,0,0" TextWrapping="Wrap" Foreground="#555"
                         Text="Tokens: %UserName% %ProjectNumber% %ProjectName% %ModelName% %DrawingName% %IssueDate% %Date% %Time%, date parts %YYYY %YY %mm %m %dd %d %HH %MM %SS, and Windows variables like %USERPROFILE%."/>
              <TextBlock x:Name="lblPathPreview" Margin="0,4,0,0" TextWrapping="Wrap" FontStyle="Italic"/>
              <RadioButton x:Name="rbSplit" Content="Save and split files by format into sub-folders:" GroupName="org" Margin="0,8,0,0"/>
              <StackPanel Orientation="Horizontal" Margin="20,0,0,0">
                <TextBlock Text="PDF folder:" VerticalAlignment="Center"/>
                <TextBox x:Name="tbPdfSub" Width="120" Margin="4,0,12,0"/>
                <TextBlock Text="DWG folder:" VerticalAlignment="Center"/>
                <TextBox x:Name="tbDwgSub" Width="120" Margin="4,0,0,0"/>
              </StackPanel>
              <RadioButton x:Name="rbSame" Content="Save all files in the same folder" GroupName="org"/>
              <StackPanel Orientation="Horizontal" Margin="0,8,0,0">
                <TextBlock Text="If a file already exists:" VerticalAlignment="Center" Margin="0,0,6,0"/>
                <ComboBox x:Name="cbExisting" Width="260"/>
              </StackPanel>
              <CheckBox x:Name="chkOpenFolder" Content="Open the export folder when finished" Margin="0,8,0,0"/>
            </StackPanel>
          </GroupBox>
          <GroupBox Header="Speed">
            <StackPanel>
              <CheckBox x:Name="chkStaging" Content="Write files to a local temp folder first, then move them (much faster on OneDrive / network folders)"/>
              <StackPanel Orientation="Horizontal" Margin="0,4,0,0">
                <TextBlock Text="Sheets per Revit export call:" VerticalAlignment="Center" Margin="0,0,6,0"/>
                <ComboBox x:Name="cbBatch" Width="70"/>
                <TextBlock VerticalAlignment="Center" Margin="8,0,0,0" Foreground="#555" TextWrapping="Wrap"
                           Text="Higher = faster; 1 = one call per sheet (slowest, most granular progress)."/>
              </StackPanel>
            </StackPanel>
          </GroupBox>
          <GroupBox Header="Before exporting, turn off on the sheets and their views">
            <WrapPanel>
              <CheckBox x:Name="chkPrepHide" Content="Temporary Hide/Isolate"/>
              <CheckBox x:Name="chkPrepWs" Content="Worksharing Display"/>
              <CheckBox x:Name="chkPrepReveal" Content="Reveal Hidden Elements"/>
              <CheckBox x:Name="chkPrepConstraints" Content="Reveal Constraints"/>
            </WrapPanel>
          </GroupBox>
          <GroupBox Header="Profiles">
            <WrapPanel>
              <Button x:Name="btnSaveProfile" Content="Save profile..."/>
              <Button x:Name="btnLoadProfile" Content="Load profile..."/>
              <Button x:Name="btnResetDefaults" Content="Reset to defaults"/>
              <TextBlock VerticalAlignment="Center" Foreground="#555" Margin="6,0,0,0"
                         Text="Profiles are .json files - keep them on a shared drive to use the same settings across the team."/>
            </WrapPanel>
          </GroupBox>
        </StackPanel>
        </ScrollViewer>
      </TabItem>
    </TabControl>
  </DockPanel>
</Window>
"""

FILTER_ALL = u"All"
FILTER_CHECKED = u"Checked only"
FILTER_BROWSER = u"Selected in Project Browser"
FILTER_OPEN = u"Open in Revit"
VSS_PREFIX = u"Revit set: "
SAVED_PREFIX = u"Saved set: "

EXISTING_LABELS = [("overwrite", u"Overwrite it"),
                   ("skip", u"Skip it (keep the old file)"),
                   ("increment", u"Keep both - add (2), (3) ...")]
ORDER_LABELS = [("list", u"As listed in Selection tab"),
                ("number", u"By sheet number"),
                ("name", u"By name")]
# DataGrid column indexes (columns are addressed by index, not x:Name)
COL_CHECK, COL_NUMBER, COL_NAME, COL_REV, COL_SIZE, COL_ORIENT, COL_TYPE, COL_FILE = range(8)

SOURCE_LABELS = {"sheet": u"Sheet", "titleblock": u"Title Block", "view": u"View",
                 "project": u"Project Info", "special": u"Special", "text": u"Text"}


class Row(object):
    """One sheet/view in the grid. Plain attributes bind in IronPython WPF."""

    def __init__(self, item):
        self.item = item
        self.Checked = False
        self.Number = item.get("number", u"")
        self.Name = item.get("name", u"")
        self.Revision = item.get("revision", u"")
        self.Size = item.get("size", u"")
        self.Orientation = item.get("orientation", u"")
        self.ViewType = item.get("view_type", u"")
        self.FileName = u""


class ParamOpt(object):
    def __init__(self, source, name):
        self.source = source
        self.name = name
        self.Display = u"%s   [%s]" % (name, SOURCE_LABELS.get(source, source))


class FieldRow(object):
    def __init__(self, source, name, sep):
        self.source = source
        self.name = name
        self.sep = sep
        self.Display = u""
        self.refresh()

    def refresh(self):
        label = (u'"%s"' % self.name) if self.source == "text" else self.name
        self.Display = u"%s   [%s]     separator: '%s'" % (
            label, SOURCE_LABELS.get(self.source, self.source), self.sep)

    def to_dict(self):
        return {"source": self.source, "name": self.name, "sep": self.sep}


def _float(text, default):
    try:
        return float(core.to_text(text).replace(u",", u"."))
    except (TypeError, ValueError):
        return default


def _int(text, default):
    try:
        return int(float(core.to_text(text)))
    except (TypeError, ValueError):
        return default


class ExportWindow(forms.WPFWindow):
    """Settings dialog. After ShowDialog(): self.result is (settings, items) or None."""

    def __init__(self, ctx):
        try:
            forms.WPFWindow.__init__(self, XAML, literal_string=True)
        except Exception:
            # older pyRevit builds: load from a temp file
            path = os.path.join(tempfile.gettempdir(), "dlc_export_sheets.xaml")
            with io.open(path, "w", encoding="utf-8") as fh:
                fh.write(XAML)
            forms.WPFWindow.__init__(self, path)
        self.ctx = ctx
        self.result = None
        self._busy = False
        self.settings = ctx["settings"]
        self.mode = self.settings.get("mode", "sheets")
        self.rows = []
        self.catalog = []
        self.fields_by_mode = {
            "sheets": [FieldRow(f["source"], f["name"], f["sep"]) for f in self.settings["naming"]["fields"]],
            "views": [FieldRow(f["source"], f["name"], f["sep"]) for f in self.settings["naming"]["view_fields"]],
        }
        self._fill_static_lists()
        self._apply_settings(self.settings)
        self._load_mode(self.mode, preselect=True)
        self._wire()
        self._refresh_all()

    # ------------------------------------------------------------- setup
    def _fill_static_lists(self):
        self.cbPaper.ItemsSource = self.ctx["paper_formats"]
        self.cbOrient.ItemsSource = core.PDF_ORIENTATIONS
        self.cbColor.ItemsSource = core.PDF_COLORS
        self.cbRasterQ.ItemsSource = core.PDF_RASTER
        self.cbDpi.ItemsSource = core.PDF_DPI
        self.cbCombineOrder.ItemsSource = [lbl for _k, lbl in ORDER_LABELS]
        self.cbExisting.ItemsSource = [lbl for _k, lbl in EXISTING_LABELS]
        self.cbDwgSetup.ItemsSource = self.ctx["dwg_setups"]
        self.cbBatch.ItemsSource = [core.to_text(n) for n in core.BATCH_SIZES]

    def _wire(self):
        self.rbSheets.Checked += self.on_mode
        self.rbViews.Checked += self.on_mode
        self.cbFilter.SelectionChanged += self.on_filter
        self.tbSearch.TextChanged += self.on_filter
        self.dgItems.AddHandler(ButtonBase.ClickEvent, RoutedEventHandler(self.on_grid_click))
        self.btnCheckAll.Click += self.on_check_all
        self.btnUncheckAll.Click += self.on_uncheck_all
        self.btnCheckSel.Click += self.on_check_sel
        self.btnUncheckSel.Click += self.on_uncheck_sel
        self.btnSaveSet.Click += self.on_save_set
        self.btnDeleteSet.Click += self.on_delete_set
        self.tbParamSearch.TextChanged += self.on_param_search
        self.lbParams.MouseDoubleClick += self.on_add_field
        self.btnAddField.Click += self.on_add_field
        self.btnRemoveField.Click += self.on_remove_field
        self.btnUp.Click += self.on_up
        self.btnDown.Click += self.on_down
        self.btnAddText.Click += self.on_add_text
        self.lbFields.SelectionChanged += self.on_field_selected
        self.tbSep.TextChanged += self.on_sep_changed
        for tb in (self.tbPrefix, self.tbSuffix, self.tbReplace):
            tb.TextChanged += self.on_naming_changed
        self.chkSkipEmpty.Click += self.on_naming_changed
        for ctl in (self.chkPdf, self.chkDwg, self.rbSeparate, self.rbCombined, self.rbBoth,
                    self.rbSplit, self.rbSame):
            ctl.Click += self.on_summary_changed
        for tb in (self.tbRoot, self.tbPdfSub, self.tbDwgSub):
            tb.TextChanged += self.on_summary_changed
        self.btnBrowse.Click += self.on_browse
        self.btnSaveProfile.Click += self.on_save_profile
        self.btnLoadProfile.Click += self.on_load_profile
        self.btnResetDefaults.Click += self.on_reset
        self.btnExport.Click += self.on_export
        self.btnCancel.Click += self.on_cancel

    # ------------------------------------------------------------- settings <-> UI
    @staticmethod
    def _select(combo, values, value, default_index=0):
        values = list(values)
        combo.SelectedIndex = values.index(value) if value in values else default_index

    def _apply_settings(self, s):
        self._busy = True
        try:
            self.rbSheets.IsChecked = s["mode"] == "sheets"
            self.rbViews.IsChecked = s["mode"] == "views"
            n = s["naming"]
            self.tbPrefix.Text = n["prefix"]
            self.tbSuffix.Text = n["suffix"]
            self.tbReplace.Text = n["replace_char"]
            self.chkSkipEmpty.IsChecked = bool(n["skip_empty"])
            p = s["pdf"]
            self._select(self.cbPaper, self.ctx["paper_formats"], p["paper"])
            self._select(self.cbOrient, core.PDF_ORIENTATIONS, p["orientation"])
            self.rbCenter.IsChecked = p["placement"] == "Center"
            self.rbOffset.IsChecked = p["placement"] == "LowerLeft"
            self.tbOffX.Text = core.to_text(p["offset_x_mm"])
            self.tbOffY.Text = core.to_text(p["offset_y_mm"])
            self.rbFit.IsChecked = bool(p["zoom_fit"])
            self.rbZoom.IsChecked = not p["zoom_fit"]
            self.tbZoom.Text = core.to_text(p["zoom_percent"])
            self.rbVector.IsChecked = not p["raster_processing"]
            self.rbRaster.IsChecked = bool(p["raster_processing"])
            self._select(self.cbColor, core.PDF_COLORS, p["color"])
            self._select(self.cbRasterQ, core.PDF_RASTER, p["raster_quality"], 2)
            self._select(self.cbDpi, core.PDF_DPI, p["dpi"], 2)
            self.chkLinksBlue.IsChecked = bool(p["view_links_blue"])
            self.chkHideRef.IsChecked = bool(p["hide_ref_planes"])
            self.chkHideTags.IsChecked = bool(p["hide_unref_tags"])
            self.chkHideScope.IsChecked = bool(p["hide_scope_boxes"])
            self.chkHideCrop.IsChecked = bool(p["hide_crop"])
            self.chkHalftone.IsChecked = bool(p["halftone_thin"])
            self.chkMask.IsChecked = bool(p["mask_coincident"])
            self.rbSeparate.IsChecked = p["output_mode"] == "separate"
            self.rbCombined.IsChecked = p["output_mode"] == "combined"
            self.rbBoth.IsChecked = p["output_mode"] == "both"
            self.tbCombinedName.Text = p["combined_name"]
            self._select(self.cbCombineOrder, [k for k, _l in ORDER_LABELS], p["combine_order"])
            d = s["dwg"]
            self._select(self.cbDwgSetup, self.ctx["dwg_setups"], d["setup"])
            self.rbMerged.IsChecked = bool(d["merged"])
            self.rbXref.IsChecked = not d["merged"]
            self.chkDeletePcp.IsChecked = bool(d["delete_pcp"])
            o = s["output"]
            self.chkPdf.IsChecked = bool(s["formats"]["pdf"])
            self.chkDwg.IsChecked = bool(s["formats"]["dwg"])
            self.tbRoot.Text = o["root"]
            self.rbSplit.IsChecked = bool(o["split_by_format"])
            self.rbSame.IsChecked = not o["split_by_format"]
            self.tbPdfSub.Text = o["pdf_subfolder"]
            self.tbDwgSub.Text = o["dwg_subfolder"]
            self._select(self.cbExisting, [k for k, _l in EXISTING_LABELS], o["existing"])
            self.chkOpenFolder.IsChecked = bool(o["open_folder"])
            self.chkStaging.IsChecked = bool(o["staging"])
            sizes = [core.to_text(n) for n in core.BATCH_SIZES]
            if core.to_text(o["batch_size"]) not in sizes:
                sizes.append(core.to_text(o["batch_size"]))
                self.cbBatch.ItemsSource = sizes
            self._select(self.cbBatch, sizes, core.to_text(o["batch_size"]))
            r = s["prep"]
            self.chkPrepHide.IsChecked = bool(r["hide_isolate"])
            self.chkPrepWs.IsChecked = bool(r["worksharing"])
            self.chkPrepReveal.IsChecked = bool(r["reveal_hidden"])
            self.chkPrepConstraints.IsChecked = bool(r["reveal_constraints"])
        finally:
            self._busy = False

    def gather_settings(self):
        s = core.default_settings()
        s["selection"]["saved_sets"] = dict(self.settings["selection"]["saved_sets"])
        s["mode"] = self.mode
        s["formats"]["pdf"] = bool(self.chkPdf.IsChecked)
        s["formats"]["dwg"] = bool(self.chkDwg.IsChecked)
        o = s["output"]
        o["root"] = core.to_text(self.tbRoot.Text).strip()
        o["split_by_format"] = bool(self.rbSplit.IsChecked)
        o["pdf_subfolder"] = core.to_text(self.tbPdfSub.Text).strip() or u"PDF"
        o["dwg_subfolder"] = core.to_text(self.tbDwgSub.Text).strip() or u"DWG"
        o["existing"] = EXISTING_LABELS[max(0, self.cbExisting.SelectedIndex)][0]
        o["open_folder"] = bool(self.chkOpenFolder.IsChecked)
        o["staging"] = bool(self.chkStaging.IsChecked)
        o["batch_size"] = _int(self.cbBatch.SelectedItem, 10)
        n = s["naming"]
        n["fields"] = [f.to_dict() for f in self.fields_by_mode["sheets"]]
        n["view_fields"] = [f.to_dict() for f in self.fields_by_mode["views"]]
        n["prefix"] = core.to_text(self.tbPrefix.Text)
        n["suffix"] = core.to_text(self.tbSuffix.Text)
        n["replace_char"] = core.to_text(self.tbReplace.Text)
        n["skip_empty"] = bool(self.chkSkipEmpty.IsChecked)
        p = s["pdf"]
        p["paper"] = core.to_text(self.cbPaper.SelectedItem or core.PDF_PAPER_DEFAULT)
        p["orientation"] = core.to_text(self.cbOrient.SelectedItem or u"Auto")
        p["placement"] = "LowerLeft" if self.rbOffset.IsChecked else "Center"
        p["offset_x_mm"] = _float(self.tbOffX.Text, 0.0)
        p["offset_y_mm"] = _float(self.tbOffY.Text, 0.0)
        p["zoom_fit"] = not bool(self.rbZoom.IsChecked)
        p["zoom_percent"] = _int(self.tbZoom.Text, 100)
        p["raster_processing"] = bool(self.rbRaster.IsChecked)
        p["color"] = core.to_text(self.cbColor.SelectedItem or u"Color")
        p["raster_quality"] = core.to_text(self.cbRasterQ.SelectedItem or u"High")
        p["dpi"] = core.to_text(self.cbDpi.SelectedItem or u"DPI300")
        p["view_links_blue"] = bool(self.chkLinksBlue.IsChecked)
        p["hide_ref_planes"] = bool(self.chkHideRef.IsChecked)
        p["hide_unref_tags"] = bool(self.chkHideTags.IsChecked)
        p["hide_scope_boxes"] = bool(self.chkHideScope.IsChecked)
        p["hide_crop"] = bool(self.chkHideCrop.IsChecked)
        p["halftone_thin"] = bool(self.chkHalftone.IsChecked)
        p["mask_coincident"] = bool(self.chkMask.IsChecked)
        if self.rbCombined.IsChecked:
            p["output_mode"] = "combined"
        elif self.rbBoth.IsChecked:
            p["output_mode"] = "both"
        else:
            p["output_mode"] = "separate"
        p["combined_name"] = core.to_text(self.tbCombinedName.Text).strip() or u"Combined"
        p["combine_order"] = ORDER_LABELS[max(0, self.cbCombineOrder.SelectedIndex)][0]
        d = s["dwg"]
        # index 0 is the "<In-session default>" entry -> stored as blank
        d["setup"] = core.to_text(self.cbDwgSetup.SelectedItem or u"") \
            if self.cbDwgSetup.SelectedIndex > 0 else u""
        d["merged"] = bool(self.rbMerged.IsChecked)
        d["delete_pcp"] = bool(self.chkDeletePcp.IsChecked)
        r = s["prep"]
        r["hide_isolate"] = bool(self.chkPrepHide.IsChecked)
        r["worksharing"] = bool(self.chkPrepWs.IsChecked)
        r["reveal_hidden"] = bool(self.chkPrepReveal.IsChecked)
        r["reveal_constraints"] = bool(self.chkPrepConstraints.IsChecked)
        return core.validate_settings(s)

    # ------------------------------------------------------------- items
    def _load_mode(self, mode, preselect=False):
        self.mode = mode
        items, catalog = self.ctx["collect"](mode)
        self.rows = [Row(it) for it in items]
        self.catalog = catalog
        if preselect:
            pre = self.ctx.get("browser_ids") or set()
            for r in self.rows:
                if r.item["id"] in pre:
                    r.Checked = True
        is_sheets = mode == "sheets"
        vis_sheet = Visibility.Visible if is_sheets else Visibility.Collapsed
        vis_view = Visibility.Collapsed if is_sheets else Visibility.Visible
        cols = self.dgItems.Columns
        for idx in (COL_NUMBER, COL_REV, COL_SIZE, COL_ORIENT):
            cols[idx].Visibility = vis_sheet
        cols[COL_TYPE].Visibility = vis_view
        self._fill_filters()
        self._fill_params()
        self._fill_fields()

    def _fill_filters(self):
        entries = [FILTER_ALL, FILTER_CHECKED, FILTER_BROWSER, FILTER_OPEN]
        if self.mode == "sheets":
            for name in sorted(self.ctx["sheet_sets"].keys(), key=core.natural_key):
                entries.append(VSS_PREFIX + name)
        for name in sorted(self.settings["selection"]["saved_sets"].keys(), key=core.natural_key):
            entries.append(SAVED_PREFIX + name)
        self._busy = True
        self.cbFilter.ItemsSource = entries
        self.cbFilter.SelectedIndex = 0
        self._busy = False

    def _filter_ids(self):
        sel = core.to_text(self.cbFilter.SelectedItem or FILTER_ALL)
        if sel == FILTER_BROWSER:
            return self.ctx.get("browser_ids") or set()
        if sel == FILTER_OPEN:
            return self.ctx.get("open_ids") or set()
        if sel.startswith(VSS_PREFIX):
            return self.ctx["sheet_sets"].get(sel[len(VSS_PREFIX):], set())
        if sel.startswith(SAVED_PREFIX):
            uids = set(self.settings["selection"]["saved_sets"].get(sel[len(SAVED_PREFIX):], []))
            return set(r.item["id"] for r in self.rows if r.item.get("uid") in uids)
        return None

    def visible_rows(self):
        ids = self._filter_ids()
        sel = core.to_text(self.cbFilter.SelectedItem or FILTER_ALL)
        q = core.to_text(self.tbSearch.Text).strip().lower()
        out = []
        for r in self.rows:
            if sel == FILTER_CHECKED and not r.Checked:
                continue
            if ids is not None and r.item["id"] not in ids:
                continue
            if q:
                hay = u" ".join([r.Number, r.Name, r.Revision, r.Size, r.ViewType, r.FileName]).lower()
                if q not in hay:
                    continue
            out.append(r)
        return out

    def checked_rows(self):
        return [r for r in self.rows if r.Checked]

    # ------------------------------------------------------------- naming
    def _fill_params(self):
        q = core.to_text(self.tbParamSearch.Text).strip().lower()
        opts = [ParamOpt(src, nm) for src, nm in self.catalog
                if not q or q in nm.lower() or q in SOURCE_LABELS.get(src, src).lower()]
        self.lbParams.ItemsSource = opts

    def _current_fields(self):
        return self.fields_by_mode[self.mode]

    def _fill_fields(self, select_index=None):
        fields = self._current_fields()
        for f in fields:
            f.refresh()
        self.lbFields.ItemsSource = list(fields)
        if select_index is not None and 0 <= select_index < len(fields):
            self.lbFields.SelectedIndex = select_index

    def _naming_now(self):
        n = {
            "prefix": core.to_text(self.tbPrefix.Text),
            "suffix": core.to_text(self.tbSuffix.Text),
            "replace_char": core.to_text(self.tbReplace.Text),
            "skip_empty": bool(self.chkSkipEmpty.IsChecked),
        }
        n["fields"] = [f.to_dict() for f in self._current_fields()]
        return n

    def _refresh_names(self):
        naming = self._naming_now()
        self.ctx["fill_time"]([r.item for r in self.rows], datetime.datetime.now())
        for r in self.rows:
            r.FileName = core.build_name(naming, r.item["values"], naming["fields"],
                                         fallback=r.Number or r.Name)
        self._refresh_preview()

    def _refresh_preview(self):
        sample = self.checked_rows() or self.rows
        self.lbPreview.ItemsSource = [r.FileName for r in sample[:8]]

    def _refresh_grid(self):
        self.dgItems.ItemsSource = self.visible_rows()
        self._refresh_count()

    def _refresh_count(self):
        shown = len(self.visible_rows())
        self.lblCount.Text = u"%d checked of %d  (%d shown)" % (
            len(self.checked_rows()), len(self.rows), shown)
        self._refresh_summary()

    def _refresh_summary(self):
        n = len(self.checked_rows())
        pdf = bool(self.chkPdf.IsChecked)
        dwg = bool(self.chkDwg.IsChecked)
        parts = []
        total = 0
        if pdf:
            if self.rbCombined.IsChecked:
                parts.append(u"PDF: 1 combined")
                total += 1 if n else 0
            elif self.rbBoth.IsChecked:
                parts.append(u"PDF: %d + 1 combined" % n)
                total += n + (1 if n else 0)
            else:
                parts.append(u"PDF: %d" % n)
                total += n
        if dwg:
            parts.append(u"DWG: %d" % n)
            total += n
        kind = u"sheets" if self.mode == "sheets" else u"views"
        self.lblSummary.Text = u"%d %s checked   |   %s   |   %d files" % (
            n, kind, u"   ".join(parts) or u"no format selected", total)
        self._refresh_path_preview()

    def _refresh_path_preview(self):
        try:
            s = self.gather_settings()
            rows = self.checked_rows() or self.rows
            items = [rows[0].item] if rows else []
            jobs = core.plan_jobs(items, s, self.ctx["project"], exists=lambda p: False)
            if jobs:
                self.lblPathPreview.Text = u"Example: " + jobs[0].path
            else:
                self.lblPathPreview.Text = u""
        except Exception as ex:
            self.lblPathPreview.Text = u"Path preview unavailable: %s" % ex

    def _refresh_all(self):
        self._refresh_names()
        self._refresh_grid()
        self.dgItems.Items.Refresh()

    # ------------------------------------------------------------- events: selection
    def on_mode(self, sender, args):
        if self._busy:
            return
        mode = "views" if self.rbViews.IsChecked else "sheets"
        if mode != self.mode:
            self._load_mode(mode)
            self._refresh_all()

    def on_filter(self, sender, args):
        if self._busy:
            return
        self._refresh_grid()

    def on_grid_click(self, sender, args):
        self._refresh_count()
        self._refresh_preview()

    def _set_checked(self, rows, value):
        for r in rows:
            r.Checked = value
        self.dgItems.Items.Refresh()
        self._refresh_names()
        self._refresh_count()

    def on_check_all(self, sender, args):
        self._set_checked(self.visible_rows(), True)

    def on_uncheck_all(self, sender, args):
        self._set_checked(self.visible_rows(), False)

    def on_check_sel(self, sender, args):
        self._set_checked(list(self.dgItems.SelectedItems), True)

    def on_uncheck_sel(self, sender, args):
        self._set_checked(list(self.dgItems.SelectedItems), False)

    def on_save_set(self, sender, args):
        rows = self.checked_rows()
        if not rows:
            forms.alert(u"Check the sheets/views you want in the set first.", title=u"Save set")
            return
        name = forms.ask_for_string(prompt=u"Name for this set of %d items:" % len(rows),
                                    title=u"Save set")
        if not name:
            return
        self.settings["selection"]["saved_sets"][core.to_text(name).strip()] = \
            [r.item["uid"] for r in rows]
        self.ctx["persist"](self.gather_settings())
        self._fill_filters()
        self._refresh_grid()

    def on_delete_set(self, sender, args):
        sel = core.to_text(self.cbFilter.SelectedItem or u"")
        if not sel.startswith(SAVED_PREFIX):
            forms.alert(u"Pick a 'Saved set' in the Show list first.", title=u"Delete set")
            return
        name = sel[len(SAVED_PREFIX):]
        self.settings["selection"]["saved_sets"].pop(name, None)
        self.ctx["persist"](self.gather_settings())
        self._fill_filters()
        self._refresh_grid()

    # ------------------------------------------------------------- events: naming
    def on_param_search(self, sender, args):
        self._fill_params()

    def on_add_field(self, sender, args):
        picked = list(self.lbParams.SelectedItems)
        if not picked:
            return
        fields = self._current_fields()
        for p in picked:
            if fields:
                if not fields[-1].sep:
                    fields[-1].sep = u" - "
            fields.append(FieldRow(p.source, p.name, u""))
        self._fill_fields(len(fields) - 1)
        self._refresh_all()

    def on_add_text(self, sender, args):
        txt = core.to_text(self.tbCustomText.Text)
        if not txt:
            return
        fields = self._current_fields()
        if fields and not fields[-1].sep:
            fields[-1].sep = u" - "
        fields.append(FieldRow("text", txt, u""))
        self.tbCustomText.Text = u""
        self._fill_fields(len(fields) - 1)
        self._refresh_all()

    def on_remove_field(self, sender, args):
        idx = self.lbFields.SelectedIndex
        fields = self._current_fields()
        if 0 <= idx < len(fields):
            fields.pop(idx)
            self._fill_fields(min(idx, len(fields) - 1))
            self._refresh_all()

    def _move(self, delta):
        idx = self.lbFields.SelectedIndex
        fields = self._current_fields()
        new = idx + delta
        if 0 <= idx < len(fields) and 0 <= new < len(fields):
            fields[idx], fields[new] = fields[new], fields[idx]
            self._fill_fields(new)
            self._refresh_all()

    def on_up(self, sender, args):
        self._move(-1)

    def on_down(self, sender, args):
        self._move(1)

    def on_field_selected(self, sender, args):
        idx = self.lbFields.SelectedIndex
        fields = self._current_fields()
        self._busy = True
        try:
            self.tbSep.Text = fields[idx].sep if 0 <= idx < len(fields) else u""
        finally:
            self._busy = False

    def on_sep_changed(self, sender, args):
        if self._busy:
            return
        idx = self.lbFields.SelectedIndex
        fields = self._current_fields()
        if 0 <= idx < len(fields):
            fields[idx].sep = core.to_text(self.tbSep.Text)
            fields[idx].refresh()
            self.lbFields.Items.Refresh()
            self._refresh_all()

    def on_naming_changed(self, sender, args):
        if self._busy:
            return
        self._refresh_all()

    # ------------------------------------------------------------- events: export tab
    def on_summary_changed(self, sender, args):
        if self._busy:
            return
        self._refresh_summary()

    def on_browse(self, sender, args):
        folder = forms.pick_folder()
        if folder:
            self.tbRoot.Text = folder

    def on_save_profile(self, sender, args):
        path = forms.save_file(file_ext="json", default_name="DLC Export Profile")
        if not path:
            return
        try:
            core.save_settings(path, self.gather_settings())
            forms.alert(u"Profile saved:\n%s" % path, title=u"Profiles")
        except Exception as ex:
            forms.alert(u"Could not save the profile: %s" % ex, title=u"Profiles")

    def on_load_profile(self, sender, args):
        path = forms.pick_file(file_ext="json")
        if not path:
            return
        s = core.load_settings(path)
        s["selection"]["saved_sets"].update(self.settings["selection"]["saved_sets"])
        self._adopt(s)

    def on_reset(self, sender, args):
        s = core.default_settings()
        s["selection"]["saved_sets"] = dict(self.settings["selection"]["saved_sets"])
        self._adopt(s)

    def _adopt(self, s):
        self.settings = s
        self.fields_by_mode = {
            "sheets": [FieldRow(f["source"], f["name"], f["sep"]) for f in s["naming"]["fields"]],
            "views": [FieldRow(f["source"], f["name"], f["sep"]) for f in s["naming"]["view_fields"]],
        }
        checked = set(r.item["id"] for r in self.checked_rows())
        self._apply_settings(s)
        if s["mode"] != self.mode:
            self._load_mode(s["mode"])
        else:
            self._fill_filters()
            self._fill_fields()
        for r in self.rows:
            r.Checked = r.item["id"] in checked
        self._refresh_all()

    # ------------------------------------------------------------- finish
    def validate(self, s):
        if not self.checked_rows():
            return u"Nothing is checked. Tick at least one sheet or view in the Selection tab."
        if not (s["formats"]["pdf"] or s["formats"]["dwg"]):
            return u"Choose at least one format (PDF or DWG) in the Export tab."
        if not s["output"]["root"]:
            return u"Set an export folder in the Export tab."
        if not self._current_fields():
            return u"The file name has no fields. Add at least one in the File Naming tab."
        return None

    def on_export(self, sender, args):
        s = self.gather_settings()
        problem = self.validate(s)
        if problem:
            forms.alert(problem, title=u"DLC Export Sheets")
            return
        self.result = (s, [r.item for r in self.rows if r.Checked])
        self.Close()

    def on_cancel(self, sender, args):
        self.result = None
        self.Close()
