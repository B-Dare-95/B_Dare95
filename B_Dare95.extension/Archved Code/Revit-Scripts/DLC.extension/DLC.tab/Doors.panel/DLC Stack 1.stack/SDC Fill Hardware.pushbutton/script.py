# -*- coding: utf-8 -*-
"""SDC - Fill Hardware from Excel

Reads a door-type -> hardware-set table from an .xlsx file and writes the
hardware set onto each door's SDC_HARDWARE parameter, matched by the door's
Type Mark.

You pick the file, the sheet, and the two columns from dropdowns filled with the
sheet's real headers - no header guessing. Ensures SDC_HARDWARE exists (instance
shared parameter bound to Doors). Modes: overwrite / fill blanks only / preview.
Reports matched, unmatched (type not in sheet), and doors with no Type Mark.

pyRevit / IronPython 2.7 - stdlib only.
"""

import os
import zipfile
from xml.etree import ElementTree as ET

from System.Collections.Generic import List

from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc
app = doc.Application
output = script.get_output()

TITLE = "SDC Fill Hardware"

SETTINGS = {
    "MAIN_SP_FILE_PATH": "",
    "SP_GROUP": "SDC_DoorRoom",
    "HARDWARE_PARAM": "SDC_HARDWARE",
    "DOOR_TYPE_ID_PARAM": "Type Mark",
    "KEY_HEADER_GUESS": ["type mark", "door type", "door mark", "mark", "type"],
    "VAL_HEADER_GUESS": ["hardware set", "hardware", "hw set", "ironmongery",
                         "hardware group", "hw"],
    "CASE_INSENSITIVE": False,
    "PARAM_UI_GROUP": DB.GroupTypeId.IdentityData,
}

SCOPE_MODEL = "Whole model"
SCOPE_VIEW = "Active view"
SCOPE_SELECTION = "Current selection"

DOOR_CAT = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Doors)
DOOR_CAT_ID = DOOR_CAT.Id.IntegerValue

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NSR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


# ---------------------------------------------------------------------------
# XLSX reader (dependency-free)
# ---------------------------------------------------------------------------
def _col_index(ref):
    letters = ""
    for ch in ref:
        if ch.isalpha():
            letters += ch
        else:
            break
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _sheet_targets(z):
    """Return [(sheet_name, part_path), ...]."""
    names = z.namelist()
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {}
    for r in rels:
        relmap[r.get("Id")] = r.get("Target")
    out = []
    for s in wb.find(_NS + "sheets"):
        tgt = relmap.get(s.get(_NSR + "id"), "")
        if tgt.startswith("/"):
            tgt = tgt[1:]
        elif not tgt.startswith("xl/"):
            tgt = "xl/" + tgt
        if tgt not in names:
            alt = "xl/" + tgt.split("/")[-1]
            tgt = alt if alt in names else tgt
        out.append((s.get("name"), tgt))
    return out


def sheet_names(path):
    z = zipfile.ZipFile(path)
    try:
        return [nm for (nm, _t) in _sheet_targets(z)]
    finally:
        z.close()


def read_xlsx(path, sheet_name=None):
    z = zipfile.ZipFile(path)
    try:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(_NS + "si"):
                shared.append("".join((t.text or "")
                                      for t in si.iter(_NS + "t")))
        targets = _sheet_targets(z)
        target = None
        if sheet_name:
            for nm, tgt in targets:
                if nm == sheet_name:
                    target = tgt
                    break
        if target is None and targets:
            target = targets[0][1]
        if not target:
            return []
        root = ET.fromstring(z.read(target))
        sd = root.find(_NS + "sheetData")
        if sd is None:
            return []
        out = []
        for row in sd.findall(_NS + "row"):
            cells = {}
            maxc = 0
            for c in row.findall(_NS + "c"):
                col = _col_index(c.get("r") or "A1")
                t = c.get("t")
                v = c.find(_NS + "v")
                val = u""
                if t == "s":
                    if v is not None and v.text is not None:
                        i = int(v.text)
                        if 0 <= i < len(shared):
                            val = shared[i]
                elif t == "inlineStr":
                    ise = c.find(_NS + "is")
                    if ise is not None:
                        val = u"".join((tt.text or "")
                                       for tt in ise.iter(_NS + "t"))
                else:
                    val = v.text if (v is not None and v.text is not None) else u""
                cells[col] = val
                if col > maxc:
                    maxc = col
            out.append([cells.get(i, u"") for i in range(1, maxc + 1)])
        return out
    finally:
        z.close()


def guess_col(headers, candidates):
    low = [(h or u"").strip().lower() for h in headers]
    for cand in candidates:
        for i, h in enumerate(low):
            if h == cand:
                return i
    for cand in candidates:
        for i, h in enumerate(low):
            if cand in h:
                return i
    return 0 if headers else -1


def build_map(rows, key_idx, val_idx, case_insensitive):
    m = {}
    for r in rows[1:]:
        if key_idx < len(r) and val_idx < len(r):
            k = (r[key_idx] or u"").strip()
            v = (r[val_idx] or u"").strip()
            if k:
                m[k.lower() if case_insensitive else k] = v
    return m


# ---------------------------------------------------------------------------
# Parameters / doors
# ---------------------------------------------------------------------------
def param_text(elem, name):
    if elem is None:
        return None
    p = elem.LookupParameter(name)
    if p is None:
        return None
    try:
        v = p.AsString()
        if v is not None and v != "":
            return v
    except Exception:
        pass
    try:
        v2 = p.AsValueString()
        if v2:
            return v2
    except Exception:
        pass
    return None


def read_door_type_id(door):
    """Read the door's type identifier (e.g. Type Mark). Type Mark is a TYPE
    parameter, so LookupParameter on the instance returns nothing - read it
    from the door's type."""
    name = SETTINGS["DOOR_TYPE_ID_PARAM"]
    v = param_text(door, name)                 # instance param, if any
    if v:
        return v
    try:
        sym = doc.GetElement(door.GetTypeId())
    except Exception:
        sym = None
    if sym is not None:
        v = param_text(sym, name)              # type param by name
        if v:
            return v
        if name == "Type Mark":
            try:
                p = sym.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_MARK)
                if p is not None:
                    s = p.AsString()
                    if s and s.strip():
                        return s
            except Exception:
                pass
    return None


def _firm_sp_path():
    p = SETTINGS["MAIN_SP_FILE_PATH"].strip()
    if not p:
        p = app.SharedParametersFilename or ""
    return p


def _binding_and_def(name):
    it = doc.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        d = it.Key
        if d is not None and d.Name == name:
            return d, it.Current
    return None, None


def _has_doors(cat_set):
    for c in cat_set:
        if c.Id.IntegerValue == DOOR_CAT_ID:
            return True
    return False


def ensure_param():
    name = SETTINGS["HARDWARE_PARAM"]
    d, b = _binding_and_def(name)
    if b is not None and _has_doors(b.Categories):
        return True, "Parameter present."
    sp_path = _firm_sp_path()
    if not sp_path or not os.path.isfile(sp_path):
        return False, "Firm shared-parameter file not found (set " \
                      "MAIN_SP_FILE_PATH)."
    original = app.SharedParametersFilename
    app.SharedParametersFilename = sp_path
    try:
        spf = app.OpenSharedParameterFile()
        if spf is None:
            return False, "Could not open the shared-parameter file."
        defn = None
        for g in spf.Groups:
            for x in g.Definitions:
                if x.Name == name:
                    defn = x
                    break
        t = DB.Transaction(doc, "SDC - Create hardware parameter")
        t.Start()
        try:
            if b is not None:
                cats = b.Categories
                if not _has_doors(cats):
                    cats.Insert(DOOR_CAT)
                    doc.ParameterBindings.ReInsert(d, b,
                                                   SETTINGS["PARAM_UI_GROUP"])
            else:
                if defn is None:
                    grp = None
                    for g in spf.Groups:
                        if g.Name == SETTINGS["SP_GROUP"]:
                            grp = g
                            break
                    if grp is None:
                        grp = spf.Groups.Create(SETTINGS["SP_GROUP"])
                    opt = DB.ExternalDefinitionCreationOptions(
                        name, DB.SpecTypeId.String.Text)
                    defn = grp.Definitions.Create(opt)
                cats = app.Create.NewCategorySet()
                cats.Insert(DOOR_CAT)
                doc.ParameterBindings.Insert(
                    defn, app.Create.NewInstanceBinding(cats),
                    SETTINGS["PARAM_UI_GROUP"])
            t.Commit()
        except Exception as ex:
            t.RollBack()
            return False, "Binding failed: {0}".format(ex)
    finally:
        app.SharedParametersFilename = original
    return True, "Parameter ensured."


def collect_doors(scope):
    if scope == SCOPE_VIEW:
        col = DB.FilteredElementCollector(doc, doc.ActiveView.Id)
    elif scope == SCOPE_SELECTION:
        sel = uidoc.Selection.GetElementIds()
        if sel is None or sel.Count == 0:
            return []
        col = DB.FilteredElementCollector(doc, List[DB.ElementId](sel))
    else:
        col = DB.FilteredElementCollector(doc)
    doors = col.OfCategory(DB.BuiltInCategory.OST_Doors) \
               .WhereElementIsNotElementType().ToElements()
    return [d for d in doors if isinstance(d, DB.FamilyInstance)]


def apply_value(door, name, new_val, wmode):
    p = door.LookupParameter(name)
    if p is None:
        return "missing"
    old = ""
    try:
        if p.StorageType == DB.StorageType.String:
            old = p.AsString() or ""
    except Exception:
        old = ""
    nv = new_val if new_val is not None else ""
    if wmode == "fill" and old.strip() != "":
        return "skip"
    if old == nv:
        return "same"
    if wmode == "preview":
        return "would"
    if p.IsReadOnly:
        return "readonly"
    try:
        p.Set(nv)
        return "set"
    except Exception:
        return "fail"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
GREEN = "#2e7d32"
AMBER = "#f9a825"
RED = "#c62828"
GREY = "#757575"


def badge(text, color, dark=False):
    return ('<span style="background:{0};color:{1};padding:2px 8px;'
            'border-radius:4px;font-size:11px;">{2}</span>').format(
                color, "#000" if dark else "#fff", text)


def render_report(rows, meta, unmatched_types, sheet_unused):
    output.print_md("# SDC \u2014 Fill Hardware from Excel")
    output.print_md("_{0}_".format(meta["stamp"]))
    output.print_md("**File:** `{0}`  |  **Sheet:** {1}".format(
        meta["file"], meta["sheet"]))
    output.print_md("**Columns:** type = {0}  |  hardware = {1}  |  "
                    "**Scope:** {2}  |  **Mode:** {3}".format(
                        meta["key_col"], meta["val_col"], meta["scope"],
                        meta["wmode_label"]))
    if meta["wmode"] == "preview":
        output.print_md("> \U0001f9ea Preview only \u2014 no changes made.")

    total = len(rows)
    matched = sum(1 for r in rows if r["status"] == "matched")
    unmatched = sum(1 for r in rows if r["status"] == "unmatched")
    notype = sum(1 for r in rows if r["status"] == "notype")
    changed = sum(r["changed"] for r in rows)
    output.print_md("Doors: **{0}**  |  Matched: **{1}**  |  Type not in "
                    "sheet: **{2}**  |  No Type Mark: **{3}**  |  {4}: **{5}**"
                    .format(total, matched, unmatched, notype,
                            "Would change" if meta["wmode"] == "preview"
                            else "Changed", changed))
    if unmatched_types:
        output.print_md("> \u26a0 Type Marks not found in the sheet: {0}".format(
            ", ".join(sorted(unmatched_types))))
    if sheet_unused:
        output.print_md("> Sheet rows never used by a door: {0}".format(
            ", ".join(sorted(sheet_unused)[:40])))

    sb = {"matched": badge("Matched", GREEN),
          "unmatched": badge("Not in sheet", AMBER, True),
          "notype": badge("No Type Mark", RED)}
    heads = ["Door", "Type Mark", "SDC_HARDWARE", "Chg", "Status"]
    html = ['<table style="border-collapse:collapse;font-size:12px;">',
            '<tr style="background:#eee;text-align:left;">'
            + "".join('<th style="padding:4px 8px;">{0}</th>'.format(h)
                      for h in heads) + "</tr>"]
    for r in rows:
        cells = [output.linkify(r["id"], r["mark"] or "-"), r["mark"] or "-",
                 r["hw"] or "-", str(r["changed"]),
                 sb.get(r["status"], r["status"])]
        html.append('<tr style="border-bottom:1px solid #ddd;">'
                    + "".join('<td style="padding:4px 8px;">{0}</td>'.format(c)
                              for c in cells) + "</tr>")
    html.append("</table>")
    try:
        output.print_html("".join(html))
    except Exception:
        data = [[r["mark"], r["hw"], str(r["changed"]), r["status"]]
                for r in rows]
        output.print_table(table_data=data,
                           columns=["Type Mark", "Hardware", "Chg", "Status"])


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Fill hardware from Excel" Width="470" SizeToContent="Height"
        ResizeMode="NoResize" WindowStartupLocation="CenterScreen"
        Background="#FFF7F7F5" FontFamily="Segoe UI">
  <Window.Resources>
    <Style TargetType="TextBlock" x:Key="Section">
      <Setter Property="Foreground" Value="#FF8A8A82"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Margin" Value="0,12,0,5"/>
    </Style>
  </Window.Resources>
  <StackPanel>
    <Border Background="#FF0F6E56" Padding="16,12">
      <StackPanel Orientation="Horizontal">
        <Border Width="34" Height="34" Background="#FF085041" CornerRadius="8"
                VerticalAlignment="Center">
          <TextBlock Text="SDC" Foreground="#FF9FE1CB" FontSize="11"
                     FontWeight="Bold" HorizontalAlignment="Center"
                     VerticalAlignment="Center"/>
        </Border>
        <StackPanel Margin="12,0,0,0" VerticalAlignment="Center">
          <TextBlock Text="Fill hardware from Excel" Foreground="#FFE1F5EE"
                     FontSize="15" FontWeight="SemiBold"/>
          <TextBlock Text="Match door Type Mark to a hardware set"
                     Foreground="#FF9FE1CB" FontSize="11"/>
        </StackPanel>
      </StackPanel>
    </Border>
    <StackPanel Margin="16,4,16,14">
      <TextBlock Text="Excel file" Style="{StaticResource Section}"/>
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <TextBox x:Name="file_lbl" IsReadOnly="True" Height="24"
                 VerticalContentAlignment="Center" Text="(no file selected)"/>
        <Button x:Name="browse_btn" Grid.Column="1" Content="Browse..."
                Click="browse_click" Width="76" Height="24" Margin="6,0,0,0"/>
      </Grid>

      <Grid Margin="0,4,0,0">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/><ColumnDefinition Width="10"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0">
          <TextBlock Text="Sheet" Style="{StaticResource Section}"/>
          <ComboBox x:Name="sheet_combo" Height="24" SelectionChanged="sheet_changed"/>
        </StackPanel>
        <StackPanel Grid.Column="2">
          <TextBlock Text="Scope" Style="{StaticResource Section}"/>
          <ComboBox x:Name="scope_combo" Height="24" SelectedIndex="0">
            <ComboBoxItem Content="Whole model"/>
            <ComboBoxItem Content="Active view"/>
            <ComboBoxItem Content="Current selection"/>
          </ComboBox>
        </StackPanel>
      </Grid>

      <Grid Margin="0,4,0,0">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/><ColumnDefinition Width="10"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0">
          <TextBlock Text="Door type column" Style="{StaticResource Section}"/>
          <ComboBox x:Name="key_combo" Height="24"/>
        </StackPanel>
        <StackPanel Grid.Column="2">
          <TextBlock Text="Hardware column" Style="{StaticResource Section}"/>
          <ComboBox x:Name="val_combo" Height="24"/>
        </StackPanel>
      </Grid>

      <CheckBox x:Name="ci_chk" Content="Ignore letter case when matching"
                Margin="0,12,0,0" Foreground="#FF5F5E5A"/>

      <Border BorderBrush="#FFE0E0DA" BorderThickness="0,1,0,0"
              Margin="0,14,0,0" Padding="0,10,0,0">
        <Grid>
          <CheckBox x:Name="fill_chk" Content="Fill blanks only"
                    VerticalAlignment="Center" HorizontalAlignment="Left"
                    Foreground="#FF5F5E5A"/>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="preview_btn" Content="Preview" Click="preview_click"
                    Width="92" Height="30" Margin="0,0,8,0"/>
            <Button x:Name="apply_btn" Content="Apply" Click="apply_click"
                    Width="92" Height="30" Background="#FF0F6E56"
                    Foreground="White" BorderBrush="#FF0F6E56"/>
          </StackPanel>
        </Grid>
      </Border>
    </StackPanel>
  </StackPanel>
</Window>
"""


class HardwareWindow(forms.WPFWindow):
    def __init__(self):
        try:
            forms.WPFWindow.__init__(self, XAML, literal_string=True)
        except TypeError:
            import tempfile
            import codecs
            tmp = os.path.join(tempfile.gettempdir(), "SDC_Hardware_ui.xaml")
            fh = codecs.open(tmp, "w", "utf-8")
            fh.write(XAML)
            fh.close()
            forms.WPFWindow.__init__(self, tmp)
        self.result = None
        self.choices = None
        self._path = None
        self._rows = []
        self._headers = []

    def browse_click(self, sender, args):
        path = forms.pick_file(file_ext="xlsx", title="Select the hardware Excel")
        if not path:
            return
        try:
            sheets = sheet_names(path)
        except Exception as ex:
            forms.alert("Could not read that file:\n{0}".format(ex), title=TITLE)
            return
        self._path = path
        self.file_lbl.Text = os.path.basename(path)
        self.sheet_combo.Items.Clear()
        for s in sheets:
            self.sheet_combo.Items.Add(s)
        if sheets:
            self.sheet_combo.SelectedIndex = 0  # triggers sheet_changed

    def _load_sheet(self):
        if not self._path:
            return
        sheet = str(self.sheet_combo.SelectedItem) if \
            self.sheet_combo.SelectedItem is not None else None
        try:
            self._rows = read_xlsx(self._path, sheet)
        except Exception:
            self._rows = []
        self._headers = self._rows[0] if self._rows else []
        self.key_combo.Items.Clear()
        self.val_combo.Items.Clear()
        for h in self._headers:
            self.key_combo.Items.Add(h)
            self.val_combo.Items.Add(h)
        if self._headers:
            self.key_combo.SelectedIndex = guess_col(
                self._headers, SETTINGS["KEY_HEADER_GUESS"])
            self.val_combo.SelectedIndex = guess_col(
                self._headers, SETTINGS["VAL_HEADER_GUESS"])

    def sheet_changed(self, sender, args):
        self._load_sheet()

    def _scope(self):
        return [SCOPE_MODEL, SCOPE_VIEW, SCOPE_SELECTION][
            self.scope_combo.SelectedIndex]

    def _gather(self):
        ci = bool(self.ci_chk.IsChecked)
        ki = self.key_combo.SelectedIndex
        vi = self.val_combo.SelectedIndex
        mp = build_map(self._rows, ki, vi, ci) if self._rows else {}
        return {
            "map": mp, "ci": ci, "scope": self._scope(),
            "fill": bool(self.fill_chk.IsChecked),
            "file": os.path.basename(self._path) if self._path else "-",
            "sheet": str(self.sheet_combo.SelectedItem)
            if self.sheet_combo.SelectedItem is not None else "-",
            "key_col": str(self.key_combo.SelectedItem)
            if self.key_combo.SelectedItem is not None else "-",
            "val_col": str(self.val_combo.SelectedItem)
            if self.val_combo.SelectedItem is not None else "-",
        }

    def _valid(self):
        if not self._path or not self._rows:
            forms.alert("Pick an Excel file first.", title=TITLE)
            return False
        if self.key_combo.SelectedIndex < 0 or self.val_combo.SelectedIndex < 0:
            forms.alert("Choose the door-type and hardware columns.", title=TITLE)
            return False
        return True

    def preview_click(self, sender, args):
        if not self._valid():
            return
        self.result = "preview"
        self.choices = self._gather()
        self.Close()

    def apply_click(self, sender, args):
        if not self._valid():
            return
        self.result = "apply"
        self.choices = self._gather()
        self.Close()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def run_tool(ch, wmode):
    if wmode != "preview":
        ok, msg = ensure_param()
        if not ok:
            forms.alert(msg, title=TITLE)
            return None

    doors = collect_doors(ch["scope"])
    if not doors:
        forms.alert("No doors found for scope '{0}'.".format(ch["scope"]),
                    title=TITLE)
        return None

    import datetime
    wlabels = {"preview": "Preview (no changes)", "fill": "Fill blanks only",
               "overwrite": "Full overwrite"}
    meta = {"scope": ch["scope"], "wmode": wmode,
            "wmode_label": wlabels.get(wmode, wmode), "file": ch["file"],
            "sheet": ch["sheet"], "key_col": ch["key_col"],
            "val_col": ch["val_col"],
            "stamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    hw_map = ch["map"]
    ci = ch["ci"]
    used = set()
    unmatched_types = set()
    rows = []
    hw_param = SETTINGS["HARDWARE_PARAM"]

    def _do(door):
        tm = read_door_type_id(door)
        key = (tm or "").strip()
        row = {"id": door.Id, "mark": tm, "hw": "", "changed": 0,
               "status": "notype"}
        if not key:
            return row
        lookup = key.lower() if ci else key
        if lookup in hw_map:
            hw = hw_map[lookup]
            used.add(lookup)
            row["hw"] = hw
            row["status"] = "matched"
            res = apply_value(door, hw_param, hw, wmode)
            if res in ("set", "would"):
                row["changed"] = 1
        else:
            row["status"] = "unmatched"
            unmatched_types.add(key)
        return row

    if wmode == "preview":
        for door in doors:
            rows.append(_do(door))
    else:
        t = DB.Transaction(doc, "SDC - Fill hardware")
        t.Start()
        with forms.ProgressBar(title="Doors {value}/{max_value}",
                               cancellable=True) as pb:
            n = len(doors)
            for i, door in enumerate(doors, 1):
                if pb.cancelled:
                    break
                pb.update_progress(i, n)
                st = DB.SubTransaction(doc)
                st.Start()
                try:
                    rows.append(_do(door))
                    st.Commit()
                except Exception:
                    st.RollBack()
        t.Commit()

    sheet_unused = set(hw_map.keys()) - used
    render_report(rows, meta, unmatched_types, sheet_unused)
    return {"matched": sum(1 for r in rows if r["status"] == "matched"),
            "changed": sum(r["changed"] for r in rows), "total": len(rows),
            "unmatched": len(unmatched_types)}


def main():
    if doc is None or doc.IsFamilyDocument:
        forms.alert("Run this in a Revit project.", title=TITLE, exitscript=True)
    win = HardwareWindow()
    win.show_dialog()
    if not win.result:
        return
    ch = win.choices
    write_mode = "fill" if ch["fill"] else "overwrite"
    if win.result == "apply":
        run_tool(ch, write_mode)
        return
    summary = run_tool(ch, "preview")
    if summary is None:
        return
    msg = ("Preview complete.\n\nMatched {0} of {1} door(s); would write {2}.\n"
           "{3} Type Mark(s) not found in the sheet.\n\nApply now ({4})?"
           ).format(summary["matched"], summary["total"], summary["changed"],
                    summary["unmatched"],
                    "fill blanks" if ch["fill"] else "overwrite")
    ans = forms.alert(msg, title=TITLE, options=["Apply changes", "Close"])
    if ans == "Apply changes":
        run_tool(ch, write_mode)


if __name__ == "__main__":
    main()
