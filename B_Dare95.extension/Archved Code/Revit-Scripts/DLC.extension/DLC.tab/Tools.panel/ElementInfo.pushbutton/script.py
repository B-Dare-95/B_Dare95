# -*- coding: utf-8 -*-
"""Click an element in the host model or any linked model and see its info.

Click the button, click an element - a window shows:
Element Name, Link (or Host model), Level and ID, plus a one-line summary
you can copy.

Tip: for elements with no clickable geometry (e.g. rooms), select the element
first, then click the button.

Changelog
  1.1.0  Single pick -> info window. Host + linked elements in one click
         (PointOnElement). Pre-selection support. Copy line + Pick Another.
         Host model name read from central path (no local "_username" suffix).
  1.0.0  Linked-only pick loop printing to the output window.
"""
from __future__ import print_function

__title__ = "Element\nInfo"
__author__ = "DLC"
__version__ = "1.1.0"

import io
import os
import re
import tempfile

from pyrevit import revit, DB, script, forms
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException


# =============================================================================
# SETTINGS - firm-level customisation, no need to touch the logic below
# =============================================================================
SETTINGS = {
    # Summary line. Placeholders: {name} {link} {level} {id}
    "LINE_TEMPLATE": u"Element Name : {name} >> Link : {link} >> Level : {level} >> ID: {id}",
    # How the "Link" value reads for elements in the host model. {model} = host file name
    "HOST_LINK_FORMAT": u"{model} (Host)",
    "NAME_SEPARATOR": u"_",
    # If a type name already starts with its family name, don't repeat it
    "SKIP_FAMILY_IF_IN_TYPE": True,
    "STRIP_RVT_EXTENSION": True,
    # If exactly one element is selected when the button is clicked, show it straight away
    "USE_PRESELECTION": True,
    "WINDOW_TITLE": u"DLC Element Info",
    "PICK_PROMPT": u"Click an element in the host or a linked model (Esc to cancel)",
    "NO_LEVEL_TEXT": u"No Level",
    "NO_NAME_TEXT": u"Unnamed",
    "NO_LINK_TEXT": u"Unknown Model",
    # Checked in order after Element.LevelId; names missing in a Revit version are skipped
    "LEVEL_PARAMS": [
        "FAMILY_LEVEL_PARAM",
        "INSTANCE_REFERENCE_LEVEL_PARAM",
        "SCHEDULE_LEVEL_PARAM",
        "WALL_BASE_CONSTRAINT",
        "STAIRS_BASE_LEVEL_PARAM",
        "ROOF_BASE_LEVEL_PARAM",
        "FAMILY_BASE_LEVEL_PARAM",
        "LEVEL_PARAM",
    ],
}

DEFAULT_TEMPLATE = u"Element Name : {name} >> Link : {link} >> Level : {level} >> ID: {id}"


# =============================================================================
# Small safe helpers
# =============================================================================
def clean(value):
    """Return stripped text, or None if empty / unreadable."""
    if value is None:
        return None
    try:
        text = u"%s" % value
    except Exception:
        return None
    text = text.strip()
    return text if text else None


def safe_attr(obj, attr):
    """Read a .NET property without letting a missing member crash the tool."""
    if obj is None:
        return None
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def id_to_int(element_id):
    """ElementId -> int. Revit 2024+ uses .Value; .IntegerValue is gone in 2026."""
    if element_id is None:
        return None
    for attr in ("Value", "IntegerValue"):
        try:
            value = getattr(element_id, attr)
        except Exception:
            continue
        if value is not None:
            try:
                return int(value)
            except Exception:
                continue
    return None


def is_valid_id(element_id):
    number = id_to_int(element_id)
    return number is not None and number != -1


def element_name(elem):
    """Element.Name via the explicit getter (IronPython-safe), then plain .Name."""
    if elem is None:
        return None
    try:
        return clean(DB.Element.Name.GetValue(elem))
    except Exception:
        pass
    return clean(safe_attr(elem, "Name"))


def param_text(elem, bip_name):
    bip = getattr(DB.BuiltInParameter, bip_name, None)
    if bip is None or elem is None:
        return None
    try:
        param = elem.get_Parameter(bip)
    except Exception:
        return None
    if param is None:
        return None
    try:
        return clean(param.AsString())
    except Exception:
        return None


# =============================================================================
# Element Name  (Family_Type)
# =============================================================================
def get_type(elem, doc):
    try:
        type_id = elem.GetTypeId()
    except Exception:
        return None
    if not is_valid_id(type_id):
        return None
    try:
        return doc.GetElement(type_id)
    except Exception:
        return None


def family_type_name(elem, doc):
    etype = get_type(elem, doc)
    family = None
    type_name = None
    if etype is not None:
        family = clean(safe_attr(etype, "FamilyName"))
        type_name = element_name(etype) or param_text(etype, "SYMBOL_NAME_PARAM")

    if family and type_name:
        if SETTINGS["SKIP_FAMILY_IF_IN_TYPE"] and type_name.startswith(family):
            return type_name
        return family + SETTINGS["NAME_SEPARATOR"] + type_name
    if type_name:
        return type_name
    if family:
        return family

    # Typeless elements (rooms, areas, spaces...)
    return (param_text(elem, "ROOM_NAME")
            or element_name(elem)
            or SETTINGS["NO_NAME_TEXT"])


# =============================================================================
# Model / link name
# =============================================================================
def strip_rvt(text):
    if text and SETTINGS["STRIP_RVT_EXTENSION"] and text.lower().endswith(u".rvt"):
        return text[:-4].strip()
    return text


def model_name(doc):
    """File name of a document without .rvt and without a local-copy "_username" suffix.

    Workshared models: read from the central path (file-based or ACC cloud).
    Otherwise: Document.Title (which may or may not include .rvt).
    """
    if doc is None:
        return None
    workshared = bool(safe_attr(doc, "IsWorkshared"))
    name = None
    if workshared:
        try:
            central = doc.GetWorksharingCentralModelPath()
            visible = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(central)
            name = clean(re.split(r"[\\/]", visible)[-1])
        except Exception:
            name = None
    if not name:
        name = strip_rvt(clean(safe_attr(doc, "Title")))
        if name and workshared:
            user = clean(safe_attr(safe_attr(doc, "Application"), "Username"))
            suffix = u"_" + user if user else None
            if suffix and name.lower().endswith(suffix.lower()) and len(name) > len(suffix):
                name = name[:-len(suffix)]
    return strip_rvt(name)


def link_display_name(link_instance, link_doc, host_doc):
    name = model_name(link_doc)
    if not name and link_instance is not None:
        name = strip_rvt(element_name(get_type(link_instance, host_doc)))
    if not name and link_instance is not None:
        # Instance name looks like "File.rvt : 1 : location <Not Shared>"
        raw = element_name(link_instance)
        if raw:
            name = strip_rvt(clean(raw.split(u" : ")[0]))
    return name or SETTINGS["NO_LINK_TEXT"]


# =============================================================================
# Level
# =============================================================================
def level_from_id(element_id, doc):
    if not is_valid_id(element_id):
        return None
    try:
        found = doc.GetElement(element_id)
    except Exception:
        return None
    if found is None or not isinstance(found, DB.Level):
        return None
    return found


def find_level(elem, doc, depth=0):
    if elem is None:
        return None

    level = level_from_id(safe_attr(elem, "LevelId"), doc)
    if level is not None:
        return level

    for bip_name in SETTINGS["LEVEL_PARAMS"]:
        bip = getattr(DB.BuiltInParameter, bip_name, None)
        if bip is None:
            continue
        try:
            param = elem.get_Parameter(bip)
        except Exception:
            continue
        if param is None:
            continue
        try:
            level = level_from_id(param.AsElementId(), doc)
        except Exception:
            level = None
        if level is not None:
            return level

    # Hosted elements (e.g. doors) fall back to their host's level - one hop only
    if depth == 0:
        host = safe_attr(elem, "Host")
        if host is not None and host is not elem:
            return find_level(host, doc, depth + 1)
    return None


def level_name(elem, doc):
    return element_name(find_level(elem, doc)) or SETTINGS["NO_LEVEL_TEXT"]


# =============================================================================
# Build the info for one element
# =============================================================================
def format_line(info):
    try:
        return SETTINGS["LINE_TEMPLATE"].format(**info)
    except (KeyError, IndexError, ValueError):
        return DEFAULT_TEMPLATE.format(**info)


def build_info(elem, elem_doc, link_instance, host_doc):
    is_linked = link_instance is not None
    if is_linked:
        link_text = link_display_name(link_instance, elem_doc, host_doc)
    else:
        host_model = model_name(host_doc) or SETTINGS["NO_LINK_TEXT"]
        try:
            link_text = SETTINGS["HOST_LINK_FORMAT"].format(model=host_model)
        except (KeyError, IndexError, ValueError):
            link_text = u"%s (Host)" % host_model
    elem_id = id_to_int(safe_attr(elem, "Id"))
    return {
        "name": family_type_name(elem, elem_doc),
        "link": link_text,
        "level": level_name(elem, elem_doc),
        "id": u"%s" % elem_id if elem_id is not None else u"?",
        "source": u"Linked" if is_linked else u"Host",
    }


def collect_info(reference, host_doc):
    """Resolve a picked Reference (host or linked). Returns (info, None) or (None, reason)."""
    linked_id = safe_attr(reference, "LinkedElementId")
    if is_valid_id(linked_id):
        link_instance = host_doc.GetElement(reference.ElementId)
        if link_instance is None:
            return None, u"The link you clicked could not be found in this model."
        try:
            link_doc = link_instance.GetLinkDocument()
        except Exception:
            link_doc = None
        if link_doc is None:
            return None, u"The link you clicked is not loaded."
        elem = link_doc.GetElement(linked_id)
        if elem is None:
            return None, u"The element could not be read from the link."
        return build_info(elem, link_doc, link_instance, host_doc), None

    elem = host_doc.GetElement(reference.ElementId)
    if elem is None:
        return None, u"The element you clicked could not be read."
    return build_info(elem, host_doc, None, host_doc), None


def preselected_info(uidoc, host_doc):
    """Info for a single pre-selected host element, else None."""
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        return None
    if len(ids) != 1:
        return None
    try:
        elem = host_doc.GetElement(ids[0])
    except Exception:
        return None
    if elem is None:
        return None
    return build_info(elem, host_doc, None, host_doc)


def copy_to_clipboard(text):
    try:
        script.clipboard_copy(text)
        return True
    except Exception:
        pass
    try:
        from System.Windows import Clipboard
        Clipboard.SetText(text)
        return True
    except Exception:
        return False


# =============================================================================
# Window
# =============================================================================
XAML = u"""<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="DLC Element Info" Width="660" SizeToContent="Height"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        ShowInTaskbar="False" Background="#FFFFFF"
        FontFamily="Segoe UI" FontSize="13">
    <Window.Resources>
        <Style x:Key="FieldLabel" TargetType="TextBlock">
            <Setter Property="Foreground" Value="#5F6B7A"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Margin" Value="0,6,18,6"/>
            <Setter Property="VerticalAlignment" Value="Top"/>
        </Style>
        <Style x:Key="FieldValue" TargetType="TextBox">
            <Setter Property="IsReadOnly" Value="True"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Foreground" Value="#1F2933"/>
            <Setter Property="TextWrapping" Value="Wrap"/>
            <Setter Property="Margin" Value="0,6,0,6"/>
            <Setter Property="Padding" Value="0"/>
        </Style>
        <Style x:Key="ActionButton" TargetType="Button">
            <Setter Property="Height" Value="30"/>
            <Setter Property="MinWidth" Value="110"/>
            <Setter Property="Margin" Value="8,0,0,0"/>
            <Setter Property="Padding" Value="12,0,12,0"/>
        </Style>
    </Window.Resources>
    <StackPanel Margin="20,16,20,18">
        <StackPanel Orientation="Horizontal" Margin="0,0,0,10">
            <Border Background="#1E6FD9" CornerRadius="3" Padding="8,2,8,2">
                <TextBlock x:Name="source_tb" Text="LINKED MODEL" Foreground="#FFFFFF"
                           FontSize="11" FontWeight="Bold"/>
            </Border>
        </StackPanel>
        <Grid>
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>
            <TextBlock Grid.Row="0" Grid.Column="0" Style="{StaticResource FieldLabel}" Text="Element Name"/>
            <TextBox x:Name="name_tb" Grid.Row="0" Grid.Column="1" Style="{StaticResource FieldValue}"/>
            <TextBlock x:Name="link_label_tb" Grid.Row="1" Grid.Column="0" Style="{StaticResource FieldLabel}" Text="Link"/>
            <TextBox x:Name="link_tb" Grid.Row="1" Grid.Column="1" Style="{StaticResource FieldValue}"/>
            <TextBlock Grid.Row="2" Grid.Column="0" Style="{StaticResource FieldLabel}" Text="Level"/>
            <TextBox x:Name="level_tb" Grid.Row="2" Grid.Column="1" Style="{StaticResource FieldValue}"/>
            <TextBlock Grid.Row="3" Grid.Column="0" Style="{StaticResource FieldLabel}" Text="ID"/>
            <TextBox x:Name="id_tb" Grid.Row="3" Grid.Column="1" Style="{StaticResource FieldValue}"/>
        </Grid>
        <Border Background="#F3F5F8" BorderBrush="#DDE2E8" BorderThickness="1"
                CornerRadius="4" Padding="10,8,10,8" Margin="0,12,0,0">
            <TextBox x:Name="line_tb" Style="{StaticResource FieldValue}" Margin="0" FontFamily="Consolas"/>
        </Border>
        <TextBlock x:Name="status_tb" Foreground="#5F6B7A" Margin="0,8,0,0" Text=" "/>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
            <Button x:Name="copy_btn" Content="Copy Line" Style="{StaticResource ActionButton}"/>
            <Button x:Name="again_btn" Content="Pick Another" Style="{StaticResource ActionButton}"/>
            <Button x:Name="close_btn" Content="Close" IsCancel="True" Style="{StaticResource ActionButton}"/>
        </StackPanel>
    </StackPanel>
</Window>
"""


def xaml_temp_path():
    """Fallback for older pyRevit builds without literal_string support."""
    path = os.path.join(tempfile.gettempdir(), "DLC_ElementInfo_%s.xaml" % __version__)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(XAML)
    return path


class InfoWindow(forms.WPFWindow):
    def __init__(self, info):
        try:
            forms.WPFWindow.__init__(self, XAML, literal_string=True)
        except TypeError:
            forms.WPFWindow.__init__(self, xaml_temp_path())
        self.action = "close"
        self.info = info
        self.Title = SETTINGS["WINDOW_TITLE"]

        is_host = info.get("source") == u"Host"
        self.source_tb.Text = u"HOST MODEL" if is_host else u"LINKED MODEL"
        self.link_label_tb.Text = u"Model" if is_host else u"Link"
        self.name_tb.Text = info["name"]
        self.link_tb.Text = info["link"]
        self.level_tb.Text = info["level"]
        self.id_tb.Text = info["id"]
        self.line_tb.Text = format_line(info)

        self.copy_btn.Click += self.on_copy
        self.again_btn.Click += self.on_again
        self.close_btn.Click += self.on_close

    def on_copy(self, sender, args):
        if copy_to_clipboard(self.line_tb.Text):
            self.status_tb.Text = u"Line copied to clipboard."
        else:
            self.status_tb.Text = (u"Could not reach the clipboard - select the line "
                                   u"above and press Ctrl+C.")

    def on_again(self, sender, args):
        self.action = "again"
        self.Close()

    def on_close(self, sender, args):
        self.action = "close"
        self.Close()


def show_window(info):
    window = InfoWindow(info)
    window.ShowDialog()
    return window.action


# =============================================================================
# Main
# =============================================================================
def pick_reference(uidoc):
    """Returns a Reference, or None if the user cancelled / picking is not possible."""
    try:
        return uidoc.Selection.PickObject(ObjectType.PointOnElement, SETTINGS["PICK_PROMPT"])
    except OperationCanceledException:
        return None
    except Exception as ex:
        forms.alert(
            u"Revit would not allow picking in this view.",
            sub_msg=u"Switch to a plan, section, elevation or 3D view, then run the "
                    u"tool again.\n\nDetails: %s" % ex,
            title=SETTINGS["WINDOW_TITLE"])
        return None


def main():
    host_doc = revit.doc
    uidoc = revit.uidoc

    info = preselected_info(uidoc, host_doc) if SETTINGS["USE_PRESELECTION"] else None
    while True:
        if info is None:
            reference = pick_reference(uidoc)
            if reference is None:
                return
            info, reason = collect_info(reference, host_doc)
            if info is None:
                forms.alert(reason, sub_msg=u"Click a different element, or press Esc to stop.",
                            title=SETTINGS["WINDOW_TITLE"])
                continue
        if show_window(info) != "again":
            return
        info = None


if __name__ == "__main__":
    main()
