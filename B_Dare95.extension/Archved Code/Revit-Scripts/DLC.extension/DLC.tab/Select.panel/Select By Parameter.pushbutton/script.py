# -*- coding: utf-8 -*-
"""DLC Select By Parameter

Pick a category (Rooms, Doors, Walls...), optionally a parameter and one or
more of its values, and the matching elements are selected and zoomed to.

Scope: Active view / Whole model / Current selection.
Revit 2025-2026, pyRevit IronPython 2.7.
"""
__title__ = "Select By\nParameter"
__author__ = "DLC"
__doc__ = ("Select elements by category, optionally filtered by a parameter "
           "value. Works on the active view, the whole model, or the current "
           "selection.")

import os
import sys
import tempfile

# The engine sits next to this script; find it wherever the button lives.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import dlc_selectby_engine as eng  # noqa: E402

# ---------------------------------------------------------------------------
# SETTINGS - firm-level options, change here without touching the logic
# ---------------------------------------------------------------------------
SETTINGS = {
    # Zoom the active view to the selected elements that are visible in it.
    "ZOOM_TO_SELECTION": True,
    # Leave out rooms/spaces/areas that are not placed (no location).
    "SKIP_UNPLACED_SPATIAL": True,
    # Offer type parameters too, listed as "[Type] Name".
    "INCLUDE_TYPE_PARAMETERS": True,
    # How many elements per category are read to build the parameter list.
    "PARAM_SAMPLE_SIZE": 300,
    # Model categories never shown (BuiltInCategory names; unknown names ignored).
    "EXCLUDED_CATEGORIES": [
        "OST_Cameras", "OST_ProjectInformation", "OST_ProjectBasePoint",
        "OST_SharedBasePoint", "OST_Materials", "OST_SunStudy",
        "OST_IOS_GeoSite", "OST_Viewers", "OST_InternalOrigin",
    ],
    # Non-model categories that are still useful to select.
    "EXTRA_CATEGORIES": ["OST_Levels", "OST_Grids"],
    # Scope the window opens on (falls back if not available).
    "DEFAULT_SCOPE": eng.SCOPE_VIEW,
}

SCOPE_LABELS = {
    eng.SCOPE_VIEW: u"Active view",
    eng.SCOPE_MODEL: u"Whole model",
    eng.SCOPE_SELECTION: u"Current selection",
}


# ---------------------------------------------------------------------------
# Revit helpers
# ---------------------------------------------------------------------------
def eid_int(element_id):
    """ElementId -> int. Revit 2024+ uses .Value; older builds .IntegerValue."""
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def element_name(DB, element):
    """Element.Name cannot be read directly from IronPython on some classes."""
    try:
        return DB.Element.Name.GetValue(element)
    except Exception:
        try:
            return element.Name
        except Exception:
            return None


def _def_name(param):
    try:
        return param.Definition.Name
    except Exception:
        return None


class RevitProvider(object):
    """Reads the model for the controller. Keeps elements keyed by int id."""

    def __init__(self, DB, doc, uidoc, settings):
        self.DB = DB
        self.doc = doc
        self.uidoc = uidoc
        self.settings = settings
        self._elements = {}   # int id -> Element
        self._cache = {}      # scope -> raw category list
        self._type_cache = {}
        self.active_view = doc.ActiveView
        self._excluded = self._bic_ids(settings.get("EXCLUDED_CATEGORIES", []))
        self._extra = self._bic_ids(settings.get("EXTRA_CATEGORIES", []))
        self._selection = list(uidoc.Selection.GetElementIds())
        self._view_ok = self._view_usable()

    # ---- setup -------------------------------------------------------
    def _bic_ids(self, names):
        out = set()
        for name in names:
            bic = getattr(self.DB.BuiltInCategory, name, None)
            if bic is not None:
                out.add(int(bic))
        return out

    def _view_usable(self):
        view = self.active_view
        if view is None:
            return False
        try:
            if view.IsTemplate:
                return False
        except Exception:
            pass
        try:
            self.DB.FilteredElementCollector(self.doc, view.Id) \
                .WhereElementIsNotElementType().GetElementCount()
            return True
        except Exception:
            return False   # sheets/schedules/browser views can refuse

    def available_scopes(self):
        scopes = []
        if self._view_ok:
            scopes.append(eng.SCOPE_VIEW)
        scopes.append(eng.SCOPE_MODEL)
        if self._selection:
            scopes.append(eng.SCOPE_SELECTION)
        return scopes

    # ---- collection --------------------------------------------------
    def _collect(self, scope):
        DB = self.DB
        if scope == eng.SCOPE_SELECTION:
            elems = [self.doc.GetElement(i) for i in self._selection]
            return [e for e in elems if e is not None]
        if scope == eng.SCOPE_VIEW:
            col = DB.FilteredElementCollector(self.doc, self.active_view.Id)
        else:
            col = DB.FilteredElementCollector(self.doc)
        return list(col.WhereElementIsNotElementType().ToElements())

    def _keep(self, element):
        cat = element.Category
        if cat is None:
            return None
        key = eid_int(cat.Id)
        if key in self._excluded:
            return None
        if key not in self._extra:
            try:
                if cat.CategoryType != self.DB.CategoryType.Model:
                    return None
            except Exception:
                return None
        if self.settings.get("SKIP_UNPLACED_SPATIAL") and \
                isinstance(element, self.DB.SpatialElement):
            if element.Location is None:
                return None
        return key, cat.Name

    def categories(self, scope):
        if scope in self._cache:
            return self._cache[scope]
        groups = {}
        names = {}
        for el in self._collect(scope):
            kept = self._keep(el)
            if kept is None:
                continue
            key, name = kept
            eid = eid_int(el.Id)
            self._elements[eid] = el
            groups.setdefault(key, []).append(eid)
            names[key] = name
        raw = [(k, names[k], ids) for k, ids in groups.items()]
        self._cache[scope] = raw
        return raw

    # ---- parameters --------------------------------------------------
    def _type_of(self, element):
        try:
            tid = element.GetTypeId()
        except Exception:
            return None
        if tid is None or tid == self.DB.ElementId.InvalidElementId:
            return None
        key = eid_int(tid)
        if key not in self._type_cache:
            self._type_cache[key] = self.doc.GetElement(tid)
        return self._type_cache[key]

    def parameter_names(self, ids):
        names = set()
        type_names = set()
        seen_types = set()
        limit = int(self.settings.get("PARAM_SAMPLE_SIZE", 300))
        for eid in ids[:limit]:
            el = self._elements.get(eid)
            if el is None:
                continue
            for p in el.Parameters:
                names.add(_def_name(p))
            if self.settings.get("INCLUDE_TYPE_PARAMETERS"):
                t = self._type_of(el)
                if t is not None and eid_int(t.Id) not in seen_types:
                    seen_types.add(eid_int(t.Id))
                    for p in t.Parameters:
                        type_names.add(_def_name(p))
        out = [eng.to_text(n) for n in names if n]
        out.extend(eng.TYPE_PREFIX + eng.to_text(n) for n in type_names if n)
        return out

    def param_text(self, param):
        """Parameter -> display text as the user sees it in Properties."""
        DB = self.DB
        if param is None:
            return None
        st = param.StorageType
        if st == DB.StorageType.String:
            return param.AsString()
        if not param.HasValue:
            return None
        text = param.AsValueString()
        if text:
            return text
        if st == DB.StorageType.Integer:
            return str(param.AsInteger())
        if st == DB.StorageType.Double:
            return "%.4f" % param.AsDouble()
        if st == DB.StorageType.ElementId:
            ref = param.AsElementId()
            if ref is None or ref == DB.ElementId.InvalidElementId:
                return None
            target = self.doc.GetElement(ref)
            if target is not None:
                return element_name(DB, target)
            return str(eid_int(ref))
        return None

    def values(self, ids, label):
        is_type = label.startswith(eng.TYPE_PREFIX)
        name = label[len(eng.TYPE_PREFIX):] if is_type else label
        out = {}
        for eid in ids:
            el = self._elements.get(eid)
            if el is None:
                continue
            host = self._type_of(el) if is_type else el
            param = host.LookupParameter(name) if host is not None else None
            try:
                out[eid] = self.param_text(param)
            except Exception:
                out[eid] = None
        return out

    # ---- result ------------------------------------------------------
    def element_ids(self, int_ids):
        return [self._elements[i].Id for i in int_ids if i in self._elements]

    def visible_in_view(self, int_ids):
        """Subset of ids that are in the active view (for zooming)."""
        if not self._view_ok:
            return []
        if eng.SCOPE_VIEW in self._cache:
            in_view = set()
            for _k, _n, ids in self._cache[eng.SCOPE_VIEW]:
                in_view.update(ids)
        else:
            in_view = set(eid_int(e.Id) for e in self._collect(eng.SCOPE_VIEW))
        return [i for i in int_ids if i in in_view]


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="DLC | Select By Parameter" Width="780" Height="580"
        MinWidth="620" MinHeight="440"
        WindowStartupLocation="CenterScreen" ShowInTaskbar="False"
        FontFamily="Segoe UI" FontSize="12" Background="#FAFAFA">
  <Grid Margin="14">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Orientation="Horizontal" Margin="0,0,0,10">
      <TextBlock Text="Look in:" FontWeight="SemiBold" VerticalAlignment="Center"
                 Margin="0,0,12,0"/>
      <RadioButton x:Name="rb_view" Content="Active view" GroupName="scope"
                   Margin="0,0,16,0" VerticalAlignment="Center"/>
      <RadioButton x:Name="rb_model" Content="Whole model" GroupName="scope"
                   Margin="0,0,16,0" VerticalAlignment="Center"/>
      <RadioButton x:Name="rb_selection" Content="Current selection"
                   GroupName="scope" VerticalAlignment="Center"/>
    </StackPanel>

    <Grid Grid.Row="1">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="260"/>
        <ColumnDefinition Width="14"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>

      <DockPanel Grid.Column="0">
        <TextBlock DockPanel.Dock="Top" Text="1. Category" FontWeight="SemiBold"
                   Margin="0,0,0,4"/>
        <TextBox x:Name="tb_cat_search" DockPanel.Dock="Top" Margin="0,0,0,6"
                 Padding="3" ToolTip="Type to filter categories"/>
        <ListBox x:Name="lb_categories"/>
      </DockPanel>

      <DockPanel Grid.Column="2">
        <TextBlock DockPanel.Dock="Top" Text="2. Parameter (optional)"
                   FontWeight="SemiBold" Margin="0,0,0,4"/>
        <ComboBox x:Name="cb_param" DockPanel.Dock="Top" Margin="0,0,0,10"
                  IsTextSearchEnabled="True"
                  ToolTip="Click, then type the first letters to jump"/>
        <TextBlock DockPanel.Dock="Top" Text="3. Values" FontWeight="SemiBold"
                   Margin="0,0,0,4"/>
        <Grid DockPanel.Dock="Top" Margin="0,0,0,6">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <TextBox x:Name="tb_val_search" Grid.Column="0" Padding="3"
                   ToolTip="Type to filter values"/>
          <Button x:Name="btn_all" Grid.Column="1" Content="All" Width="48"
                  Margin="6,0,0,0" ToolTip="Tick all values shown"/>
          <Button x:Name="btn_none" Grid.Column="2" Content="None" Width="48"
                  Margin="4,0,0,0" ToolTip="Untick all values shown"/>
        </Grid>
        <ListBox x:Name="lb_values"/>
      </DockPanel>
    </Grid>

    <DockPanel Grid.Row="2" Margin="0,12,0,0" LastChildFill="True">
      <Button x:Name="btn_cancel" DockPanel.Dock="Right" Content="Cancel"
              Width="90" Height="28" Margin="8,0,0,0" IsCancel="True"/>
      <Button x:Name="btn_ok" DockPanel.Dock="Right" Content="Select"
              Width="110" Height="28" IsDefault="True" FontWeight="SemiBold"/>
      <TextBlock x:Name="tx_status" VerticalAlignment="Center"
                 TextWrapping="Wrap" Foreground="#333"/>
    </DockPanel>
  </Grid>
</Window>
"""

XAML_NAMES = ["rb_view", "rb_model", "rb_selection", "tb_cat_search",
              "lb_categories", "cb_param", "tb_val_search", "btn_all",
              "btn_none", "lb_values", "btn_cancel", "btn_ok", "tx_status"]


def build_window_class(forms, Controls):
    """Created at run time so this module imports without pyRevit/WPF."""

    class SelectWindow(forms.WPFWindow):
        def __init__(self, controller):
            try:
                forms.WPFWindow.__init__(self, XAML, literal_string=True)
            except TypeError:
                # Older pyRevit builds only accept a file path.
                path = os.path.join(tempfile.gettempdir(), "dlc_selectby.xaml")
                with open(path, "wb") as fh:
                    fh.write(XAML.encode("utf-8"))
                forms.WPFWindow.__init__(self, path)
            self.ctrl = controller
            self.result = None
            self._busy = False
            self._radios = {eng.SCOPE_VIEW: self.rb_view,
                            eng.SCOPE_MODEL: self.rb_model,
                            eng.SCOPE_SELECTION: self.rb_selection}
            for scope, rb in self._radios.items():
                rb.IsEnabled = scope in controller.scopes
                rb.Tag = scope
                rb.Checked += self.on_scope
            if not controller.scopes or eng.SCOPE_SELECTION not in controller.scopes:
                self.rb_selection.ToolTip = "Select some elements first"
            self.tb_cat_search.TextChanged += self.on_cat_search
            self.lb_categories.SelectionChanged += self.on_category
            self.cb_param.SelectionChanged += self.on_param
            self.tb_val_search.TextChanged += self.on_val_search
            self.btn_all.Click += self.on_all
            self.btn_none.Click += self.on_none
            self.btn_ok.Click += self.on_ok
            self.btn_cancel.Click += self.on_cancel
            self._busy = True
            if controller.scope in self._radios:
                self._radios[controller.scope].IsChecked = True
            self._busy = False
            self.refresh_all()
            self.tb_cat_search.Focus()

        # ---- rendering -----------------------------------------------
        def refresh_all(self):
            self.refresh_categories()
            self.refresh_params()
            self.refresh_values()
            self.refresh_status()

        def refresh_categories(self):
            self._busy = True
            self.lb_categories.Items.Clear()
            selected = None
            for c in self.ctrl.visible_categories():
                item = Controls.ListBoxItem()
                item.Content = c.label
                item.Tag = c.key
                self.lb_categories.Items.Add(item)
                if self.ctrl.category is not None and c.key == self.ctrl.category.key:
                    selected = item
            if selected is not None:
                self.lb_categories.SelectedItem = selected
                self.lb_categories.ScrollIntoView(selected)
            self._busy = False

        def refresh_params(self):
            self._busy = True
            self.cb_param.Items.Clear()
            enabled = self.ctrl.category is not None
            for name in self.ctrl.param_choices():
                self.cb_param.Items.Add(name)
            self.cb_param.SelectedItem = self.ctrl.param or eng.NO_FILTER_LABEL
            self.cb_param.IsEnabled = enabled
            self._busy = False

        def refresh_values(self):
            self._busy = True
            self.lb_values.Items.Clear()
            for v in self.ctrl.visible_values():
                cb = Controls.CheckBox()
                cb.Content = v.label
                cb.Tag = v.value
                cb.IsChecked = v.value in self.ctrl.checked
                cb.Checked += self.on_value_toggle
                cb.Unchecked += self.on_value_toggle
                self.lb_values.Items.Add(cb)
            has_param = self.ctrl.param is not None
            for w in (self.lb_values, self.tb_val_search, self.btn_all,
                      self.btn_none):
                w.IsEnabled = has_param
            self._busy = False

        def refresh_status(self):
            self.tx_status.Text = self.ctrl.status_text()
            self.btn_ok.IsEnabled = self.ctrl.can_apply()

        # ---- events --------------------------------------------------
        def on_scope(self, sender, args):
            if self._busy:
                return
            self.ctrl.set_scope(sender.Tag)
            self.refresh_all()

        def on_cat_search(self, sender, args):
            self.ctrl.category_search = self.tb_cat_search.Text
            self.refresh_categories()

        def on_category(self, sender, args):
            if self._busy:
                return
            item = self.lb_categories.SelectedItem
            if item is None:
                return
            self.ctrl.set_category(item.Tag)
            self.refresh_params()
            self.refresh_values()
            self.refresh_status()

        def on_param(self, sender, args):
            if self._busy:
                return
            self.ctrl.value_search = u""
            self._busy = True
            self.tb_val_search.Text = ""
            self._busy = False
            self.ctrl.set_param(self.cb_param.SelectedItem)
            self.refresh_values()
            self.refresh_status()

        def on_val_search(self, sender, args):
            if self._busy:
                return
            self.ctrl.value_search = self.tb_val_search.Text
            self.refresh_values()

        def on_value_toggle(self, sender, args):
            if self._busy:
                return
            self.ctrl.set_checked(sender.Tag, bool(sender.IsChecked))
            self.refresh_status()

        def on_all(self, sender, args):
            self.ctrl.check_visible(True)
            self.refresh_values()
            self.refresh_status()

        def on_none(self, sender, args):
            self.ctrl.check_visible(False)
            self.refresh_values()
            self.refresh_status()

        def on_ok(self, sender, args):
            if not self.ctrl.can_apply():
                return
            self.result = self.ctrl.matched_ids()
            self.Close()

        def on_cancel(self, sender, args):
            self.result = None
            self.Close()

    return SelectWindow


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def apply_selection(provider, uidoc, int_ids, settings, List, ElementId):
    """Select the ids, zoom to the visible ones. Returns (selected, zoomed)."""
    ids = provider.element_ids(int_ids)
    uidoc.Selection.SetElementIds(List[ElementId](ids))
    zoomed = 0
    if settings.get("ZOOM_TO_SELECTION") and ids:
        visible = provider.element_ids(provider.visible_in_view(int_ids))
        if visible:
            try:
                uidoc.ShowElements(List[ElementId](visible))
                zoomed = len(visible)
            except Exception:
                zoomed = 0
    return len(ids), zoomed


def main():
    from pyrevit import revit, DB, forms, script
    import clr
    clr.AddReference("PresentationFramework")
    from System.Windows import Controls
    from System.Collections.Generic import List

    doc = revit.doc
    uidoc = revit.uidoc
    if doc is None or uidoc is None:
        forms.alert("Open a model first.", title="Select By Parameter")
        return

    provider = RevitProvider(DB, doc, uidoc, SETTINGS)
    controller = eng.SelectController(provider)
    default = SETTINGS.get("DEFAULT_SCOPE")
    if default in controller.scopes and controller.scope != default:
        controller.set_scope(default)

    if not controller.categories and controller.scope == eng.SCOPE_VIEW \
            and eng.SCOPE_MODEL in controller.scopes:
        controller.set_scope(eng.SCOPE_MODEL)

    window = build_window_class(forms, Controls)(controller)
    window.ShowDialog()
    if not window.result:
        return

    apply_selection(provider, uidoc, window.result, SETTINGS, List,
                    DB.ElementId)


if __name__ == "__main__":
    main()
