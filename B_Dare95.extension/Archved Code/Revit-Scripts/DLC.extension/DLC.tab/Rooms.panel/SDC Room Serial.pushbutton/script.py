# -*- coding: utf-8 -*-
"""SDC - Room Serial

Writes a room serial onto every room, mirroring the door number:

    SDC_Room_Serial = SDC_G_BUILDING CODE . SDC_G_LEVEL CODE . Number

The building and level codes are the firm shared parameters already on rooms;
Number is the built-in room Number. The serial is written to a new instance
shared parameter (SDC_Room_Serial), created in the firm main SP file and bound
to Rooms.

Run modes: full overwrite / fill blanks only / preview. Colour-coded report.
pyRevit / IronPython 2.7, stdlib only.
"""

import os
import datetime

from System.Collections.Generic import List

from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc
app = doc.Application
output = script.get_output()

TITLE = "SDC Room Serial"

SETTINGS = {
    "MAIN_SP_FILE_PATH": "",           # "" => whatever Revit points at
    "SP_GROUP": "SDC_DoorRoom",

    "ROOM_BUILDING_CODE": "SDC_G_BUILDING CODE",
    "ROOM_LEVEL_CODE": "SDC_G_LEVEL CODE",
    "ROOM_SERIAL_PARAM": "SDC_Room_Serial",

    "SERIAL_SEPARATOR": ".",
    "SKIP_UNPLACED": True,             # ignore rooms with no location/zero area

    "PARAM_UI_GROUP": DB.GroupTypeId.IdentityData,
    "EMPTY_VALUE": "",
}

SCOPE_MODEL = "Whole model"
SCOPE_VIEW = "Active view"
SCOPE_SELECTION = "Current selection"

ROOM_CAT = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Rooms)
ROOM_CAT_ID = ROOM_CAT.Id.IntegerValue


# ---------------------------------------------------------------------------
# Parameters
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


def _has_rooms(cat_set):
    for c in cat_set:
        if c.Id.IntegerValue == ROOM_CAT_ID:
            return True
    return False


def _is_bound_to_rooms(name):
    d, b = _binding_and_def(name)
    if b is None:
        return False
    return _has_rooms(b.Categories)


def ensure_room_param():
    """Ensure SDC_Room_Serial is an instance shared param bound to Rooms.
    Returns (ok, message, sp_path)."""
    name = SETTINGS["ROOM_SERIAL_PARAM"]
    if _is_bound_to_rooms(name):
        return True, "Parameter already present.", _firm_sp_path()

    sp_path = _firm_sp_path()
    if not sp_path or not os.path.isfile(sp_path):
        return (False, "Firm shared-parameter file not found. Set "
                "MAIN_SP_FILE_PATH or point Revit at it. Looked for: '{0}'"
                .format(sp_path), sp_path)

    original = app.SharedParametersFilename
    app.SharedParametersFilename = sp_path
    try:
        spf = app.OpenSharedParameterFile()
        if spf is None:
            return False, "Could not open the shared-parameter file.", sp_path

        # If bound elsewhere (e.g. another category) add Rooms, else create.
        d_internal, b_existing = _binding_and_def(name)
        defn = None
        for g in spf.Groups:
            for d in g.Definitions:
                if d.Name == name:
                    defn = d
                    break

        t = DB.Transaction(doc, "SDC - Create room serial parameter")
        t.Start()
        try:
            if b_existing is not None:
                cats = b_existing.Categories
                if not _has_rooms(cats):
                    cats.Insert(ROOM_CAT)
                    doc.ParameterBindings.ReInsert(
                        d_internal, b_existing, SETTINGS["PARAM_UI_GROUP"])
            else:
                if defn is None:
                    group = None
                    for g in spf.Groups:
                        if g.Name == SETTINGS["SP_GROUP"]:
                            group = g
                            break
                    if group is None:
                        group = spf.Groups.Create(SETTINGS["SP_GROUP"])
                    opt = DB.ExternalDefinitionCreationOptions(
                        name, DB.SpecTypeId.String.Text)
                    defn = group.Definitions.Create(opt)
                cats = app.Create.NewCategorySet()
                cats.Insert(ROOM_CAT)
                doc.ParameterBindings.Insert(
                    defn, app.Create.NewInstanceBinding(cats),
                    SETTINGS["PARAM_UI_GROUP"])
            t.Commit()
        except Exception as ex:
            t.RollBack()
            return False, "Binding failed: {0}".format(ex), sp_path
    finally:
        app.SharedParametersFilename = original
    return True, "Parameter ensured.", sp_path


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------
def collect_rooms(scope):
    if scope == SCOPE_VIEW:
        col = DB.FilteredElementCollector(doc, doc.ActiveView.Id)
    elif scope == SCOPE_SELECTION:
        sel = uidoc.Selection.GetElementIds()
        if sel is None or sel.Count == 0:
            return []
        col = DB.FilteredElementCollector(doc, List[DB.ElementId](sel))
    else:
        col = DB.FilteredElementCollector(doc)
    rooms = col.OfCategory(DB.BuiltInCategory.OST_Rooms) \
               .WhereElementIsNotElementType().ToElements()
    out = []
    for r in rooms:
        if not isinstance(r, DB.SpatialElement):
            continue
        if SETTINGS["SKIP_UNPLACED"]:
            try:
                if r.Location is None or r.Area <= 0:
                    continue
            except Exception:
                pass
        out.append(r)
    return out


def room_number(room):
    try:
        v = room.Number
        if v:
            return v
    except Exception:
        pass
    return param_text(room, "Number")


def room_level(room):
    try:
        lvl = doc.GetElement(room.LevelId)
        if lvl is not None:
            return lvl.Name
    except Exception:
        pass
    return "-"


def apply_value(room, name, new_val, wmode):
    p = room.LookupParameter(name)
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


def process_room(room, wmode):
    building = param_text(room, SETTINGS["ROOM_BUILDING_CODE"])
    level = param_text(room, SETTINGS["ROOM_LEVEL_CODE"])
    number = room_number(room)

    have_all = bool(building) and bool(level) and bool(number)
    serial = SETTINGS["SERIAL_SEPARATOR"].join([building, level, number]) \
        if have_all else SETTINGS["EMPTY_VALUE"]

    res = apply_value(room, SETTINGS["ROOM_SERIAL_PARAM"], serial, wmode)
    changed = 1 if res in ("set", "would") else 0
    status = "ok" if have_all else "partial"

    return {
        "id": room.Id, "name": (room_number(room) or "-"),
        "rname": param_text(room, "Name") or "-",
        "level": room_level(room), "bldg": building or "-", "lvl": level or "-",
        "num": number or "-", "serial": serial or "-",
        "changed": changed, "status": status,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
GREEN = "#2e7d32"
AMBER = "#f9a825"
GREY = "#757575"


def badge(text, color, dark=False):
    fg = "#000" if dark else "#fff"
    return ('<span style="background:{0};color:{1};padding:2px 8px;'
            'border-radius:4px;font-size:11px;">{2}</span>').format(
                color, fg, text)


def render_report(rows, meta):
    output.print_md("# SDC \u2014 Room Serial")
    output.print_md("_{0}_".format(meta["stamp"]))
    output.print_md("**Scope:** {0}  |  **Write mode:** {1}".format(
        meta["scope"], meta["wmode_label"]))
    output.print_md("**Firm SP file:** `{0}`".format(meta["sp_path"]))
    if meta["wmode"] == "preview":
        output.print_md("> \U0001f9ea Preview only \u2014 no changes made.")

    total = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    partial = sum(1 for r in rows if r["status"] == "partial")
    changed = sum(r["changed"] for r in rows)
    output.print_md("Rooms: **{0}**  |  Serial written: **{1}**  |  Partial "
                    "(missing code): **{2}**  |  {3}: **{4}**".format(
                        total, ok, partial,
                        "Would change" if meta["wmode"] == "preview"
                        else "Changed", changed))

    sb = {"ok": badge("OK", GREEN), "partial": badge("Partial", AMBER, True)}
    heads = ["Room", "Level", "Bldg", "Lvl", "Number", "SDC_Room_Serial",
             "Chg", "Status"]
    html = ['<table style="border-collapse:collapse;font-size:12px;">',
            '<tr style="background:#eee;text-align:left;">'
            + "".join('<th style="padding:4px 8px;">{0}</th>'.format(h)
                      for h in heads) + "</tr>"]
    for r in rows:
        cells = [output.linkify(r["id"], r["rname"]), r["level"], r["bldg"],
                 r["lvl"], r["num"], r["serial"], str(r["changed"]),
                 sb.get(r["status"], r["status"])]
        html.append('<tr style="border-bottom:1px solid #ddd;">'
                    + "".join('<td style="padding:4px 8px;">{0}</td>'.format(c)
                              for c in cells) + "</tr>")
    html.append("</table>")
    try:
        output.print_html("".join(html))
    except Exception:
        data = [[r["rname"], r["level"], r["bldg"], r["lvl"], r["num"],
                 r["serial"], str(r["changed"]), r["status"]] for r in rows]
        output.print_table(table_data=data, columns=heads)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Room serial" Width="440" SizeToContent="Height"
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
          <TextBlock Text="Room serial" Foreground="#FFE1F5EE" FontSize="15"
                     FontWeight="SemiBold"/>
          <TextBlock Text="BUILDING . LEVEL . NUMBER  into SDC_Room_Serial"
                     Foreground="#FF9FE1CB" FontSize="11"/>
        </StackPanel>
      </StackPanel>
    </Border>
    <StackPanel Margin="16,4,16,14">
      <TextBlock Text="Which rooms" Style="{StaticResource Section}"/>
      <StackPanel Orientation="Horizontal">
        <RadioButton x:Name="scope_model" GroupName="scope" Content="Whole model"
                     IsChecked="True" Checked="scope_changed" Margin="0,0,16,0"/>
        <RadioButton x:Name="scope_view" GroupName="scope" Content="Active view"
                     Checked="scope_changed" Margin="0,0,16,0"/>
        <RadioButton x:Name="scope_sel" GroupName="scope" Content="Selection"
                     Checked="scope_changed"/>
      </StackPanel>
      <TextBlock x:Name="room_count" Foreground="#FF185FA5" FontSize="12"
                 Margin="0,6,0,0"/>
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
    <Border Background="#FFEFEFEA" BorderBrush="#FFE0E0DA"
            BorderThickness="0,1,0,0" Padding="16,6">
      <TextBlock x:Name="sp_path_lbl" Foreground="#FFA0A099" FontSize="11"
                 TextTrimming="CharacterEllipsis"/>
    </Border>
  </StackPanel>
</Window>
"""


class RoomSerialWindow(forms.WPFWindow):
    def __init__(self):
        try:
            forms.WPFWindow.__init__(self, XAML, literal_string=True)
        except TypeError:
            import tempfile
            import codecs
            tmp = os.path.join(tempfile.gettempdir(), "SDC_RoomSerial_ui.xaml")
            fh = codecs.open(tmp, "w", "utf-8")
            fh.write(XAML)
            fh.close()
            forms.WPFWindow.__init__(self, tmp)
        self.result = None
        self.choices = None
        self._load_config()
        self.sp_path_lbl.Text = "SP file: " + (_firm_sp_path()
                                               or "(set MAIN_SP_FILE_PATH)")
        self._update_count()

    def _current_scope(self):
        if self.scope_view.IsChecked:
            return SCOPE_VIEW
        if self.scope_sel.IsChecked:
            return SCOPE_SELECTION
        return SCOPE_MODEL

    def _update_count(self):
        try:
            n = len(collect_rooms(self._current_scope()))
        except Exception:
            n = 0
        self.room_count.Text = "{0} {1} in scope".format(
            n, "room" if n == 1 else "rooms")

    def _gather(self):
        return {"scope": self._current_scope(),
                "fill": bool(self.fill_chk.IsChecked)}

    def _load_config(self):
        try:
            cfg = script.get_config("room_serial")
            sc = cfg.get_option("scope", SCOPE_MODEL)
            self.scope_model.IsChecked = (sc == SCOPE_MODEL)
            self.scope_view.IsChecked = (sc == SCOPE_VIEW)
            self.scope_sel.IsChecked = (sc == SCOPE_SELECTION)
            self.fill_chk.IsChecked = bool(cfg.get_option("fill", False))
        except Exception:
            pass

    def _save_config(self):
        try:
            cfg = script.get_config("room_serial")
            cfg.scope = self._current_scope()
            cfg.fill = bool(self.fill_chk.IsChecked)
            script.save_config()
        except Exception:
            pass

    def scope_changed(self, sender, args):
        self._update_count()

    def preview_click(self, sender, args):
        self.result = "preview"
        self.choices = self._gather()
        self._save_config()
        self.Close()

    def apply_click(self, sender, args):
        self.result = "apply"
        self.choices = self._gather()
        self._save_config()
        self.Close()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def run_tool(ch, wmode):
    sp_path = _firm_sp_path()
    if wmode != "preview":
        ok, msg, sp_path = ensure_room_param()
        if not ok:
            forms.alert(msg, title=TITLE)
            return None

    rooms = collect_rooms(ch["scope"])
    if not rooms:
        forms.alert("No rooms found for scope '{0}'.".format(ch["scope"]),
                    title=TITLE)
        return None

    now = datetime.datetime.now()
    wlabels = {"preview": "Preview (no changes)", "fill": "Fill blanks only",
               "overwrite": "Full overwrite"}
    meta = {"scope": ch["scope"], "wmode": wmode,
            "wmode_label": wlabels.get(wmode, wmode), "sp_path": sp_path,
            "stamp": now.strftime("%Y-%m-%d %H:%M:%S")}

    rows = []
    if wmode == "preview":
        for room in rooms:
            try:
                rows.append(process_room(room, wmode))
            except Exception:
                pass
    else:
        t = DB.Transaction(doc, "SDC - Room serial")
        t.Start()
        with forms.ProgressBar(title="Rooms {value}/{max_value}",
                               cancellable=True) as pb:
            n = len(rooms)
            for i, room in enumerate(rooms, 1):
                if pb.cancelled:
                    break
                pb.update_progress(i, n)
                st = DB.SubTransaction(doc)
                st.Start()
                try:
                    rows.append(process_room(room, wmode))
                    st.Commit()
                except Exception:
                    st.RollBack()
        t.Commit()

    render_report(rows, meta)
    return {"changed": sum(r["changed"] for r in rows), "total": len(rows),
            "partial": sum(1 for r in rows if r["status"] == "partial")}


def main():
    if doc is None or doc.IsFamilyDocument:
        forms.alert("Run this in a Revit project.", title=TITLE, exitscript=True)

    win = RoomSerialWindow()
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
    msg = ("Preview complete.\n\nWould set {0} serial(s) on {1} room(s).\n"
           "{2} partial (missing building/level code).\n\nApply now ({3})?"
           ).format(summary["changed"], summary["total"], summary["partial"],
                    "fill blanks" if ch["fill"] else "overwrite")
    ans = forms.alert(msg, title=TITLE, options=["Apply changes", "Close"])
    if ans == "Apply changes":
        run_tool(ch, write_mode)


if __name__ == "__main__":
    main()
