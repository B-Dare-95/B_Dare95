# -*- coding: utf-8 -*-
__author__  = "Mohamed Bedair"
__version__ = "2.0.0"
__doc__ = """__________________________________________________
Description:

Pins or unpins elements in bulk: in the current view, in views you choose, or in the whole project.
You can limit it to certain model categories, and a summary shows how many elements were changed.
__________________________________________________
How-to:

-> Click on the button
-> Choose Pin or Unpin
-> Choose Current View, Selected Views or Entire Project
-> Optionally turn on the category filter and check categories
-> Click "Run" and check the summary in the output window
__________________________________________________
Author: Mohamed Bedair"""

# ─────────────────────────────────────────────────────────────────────────────
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Windows import (
    Visibility, MessageBox, MessageBoxButton, MessageBoxImage
)
from System.Windows.Controls import CheckBox

from Autodesk.Revit.DB import (
    FilteredElementCollector, Transaction, View, ViewType, CategoryType
)
from pyrevit import script
import bd_core as bd

doc = __revit__.ActiveUIDocument.Document

# ── Data Collection ───────────────────────────────────────────────────────────
_SKIP_VT = {
    int(ViewType.SystemBrowser),
    int(ViewType.ProjectBrowser),
    int(ViewType.Undefined),
    int(ViewType.Internal),
}

def collect_views():
    result = []
    for v in FilteredElementCollector(doc).OfClass(View).ToElements():
        if not v.IsTemplate and int(v.ViewType) not in _SKIP_VT:
            result.append(v)
    return sorted(result, key=lambda v: (str(v.ViewType), v.Name))

def collect_model_cats():
    names = []
    for cat in doc.Settings.Categories:
        try:
            if cat.CategoryType == CategoryType.Model:
                names.append(cat.Name)
        except Exception:
            pass
    return sorted(names)

ALL_VIEWS = collect_views()
ALL_CATS  = collect_model_cats()

# ── XAML ──────────────────────────────────────────────────────────────────────
# Window layout: ui.xaml next to this script (shared colours and styles: lib/bd_theme.xaml)

# ── Dialog Class ──────────────────────────────────────────────────────────────
class PinUnpinDialog(object):
    """
    WPF dialog for Pin / Unpin Manager v2.

    Two key design decisions for IronPython 2.7:

    1. CHECKBOX LISTS via ScrollViewer + StackPanel (not ListBox).
       No selection-highlight conflicts; check state is tracked
       independently in Python dicts.

    2. STATE PERSISTENCE across search redraws.
       _view_checked / _cat_checked dicts store {key: bool} and
       are read/written by per-item Checked/Unchecked handlers.
       When the search filter changes, the panel is cleared and
       rebuilt; IsChecked is seeded from the dict so check marks survive.
    """

    def __init__(self):
        self.result        = None
        self._lock         = [False]     # re-entrancy guard for radio groups

        # Persistent check-state dicts (survive search filter changes)
        self._view_checked = {v.Id: False for v in ALL_VIEWS}
        self._cat_checked  = {n: False for n in ALL_CATS}

        self.win = bd.load_window(__file__)

        # ── Named controls ────────────────────────────────────────────────
        self.btn_pin         = self.win.FindName('btn_pin')
        self.btn_unpin       = self.win.FindName('btn_unpin')

        self.btn_cur         = self.win.FindName('btn_cur')
        self.btn_sel         = self.win.FindName('btn_sel')
        self.btn_proj        = self.win.FindName('btn_proj')
        self.pnl_views       = self.win.FindName('pnl_views')
        self.panel_views     = self.win.FindName('panel_views')
        self.txt_view_search = self.win.FindName('txt_view_search')

        self.btn_cat_tog     = self.win.FindName('btn_cat_tog')
        self.pnl_cats        = self.win.FindName('pnl_cats')
        self.panel_cats      = self.win.FindName('panel_cats')
        self.txt_cat_search  = self.win.FindName('txt_cat_search')

        self.btn_cancel = self.win.FindName('btn_cancel')
        self.btn_run    = self.win.FindName('btn_run')

        # Cache shared CheckBox style (avoids repeated ResourceDictionary look-ups)
        self._chk_style = self.win.Resources['DarkChk']

        # ── Initial list render (no filter active yet) ────────────────────
        self._render_views('')
        self._render_cats('')

        # ── Wire events ───────────────────────────────────────────────────
        self.btn_pin.Checked     += self._on_action
        self.btn_unpin.Checked   += self._on_action
        self.btn_pin.Unchecked   += self._guard
        self.btn_unpin.Unchecked += self._guard

        self.btn_cur.Checked    += self._on_scope
        self.btn_sel.Checked    += self._on_scope
        self.btn_proj.Checked   += self._on_scope
        self.btn_cur.Unchecked  += self._guard
        self.btn_sel.Unchecked  += self._guard
        self.btn_proj.Unchecked += self._guard

        self.txt_view_search.TextChanged += self._on_view_search
        self.txt_cat_search.TextChanged  += self._on_cat_search

        self.btn_cat_tog.Checked   += self._on_cat_tog
        self.btn_cat_tog.Unchecked += self._on_cat_tog

        self.btn_cancel.Click += self._cancel
        self.btn_run.Click    += self._run

    # ── CheckBox factories ────────────────────────────────────────────────────
    def _make_view_cb(self, label, view_id):
        """Create a styled CheckBox for a view entry."""
        cb           = CheckBox()
        cb.Content   = label
        cb.Style     = self._chk_style
        cb.IsChecked = self._view_checked.get(view_id, False)

        # Default-arg captures view_id correctly in IronPython 2.7 closures
        def on_toggle(s, e, vid=view_id):
            self._view_checked[vid] = bool(s.IsChecked)

        cb.Checked   += on_toggle
        cb.Unchecked += on_toggle
        return cb

    def _make_cat_cb(self, name):
        """Create a styled CheckBox for a category entry."""
        cb           = CheckBox()
        cb.Content   = name
        cb.Style     = self._chk_style
        cb.IsChecked = self._cat_checked.get(name, False)

        def on_toggle(s, e, n=name):
            self._cat_checked[n] = bool(s.IsChecked)

        cb.Checked   += on_toggle
        cb.Unchecked += on_toggle
        return cb

    # ── List renderers ────────────────────────────────────────────────────────
    def _render_views(self, filter_text):
        """Clear and rebuild the view checkbox panel, respecting the search filter."""
        ft = filter_text.strip().lower()
        self.panel_views.Children.Clear()
        for v in ALL_VIEWS:
            label = u"[{}]  {}".format(str(v.ViewType), v.Name)
            if ft and ft not in label.lower():
                continue
            self.panel_views.Children.Add(
                self._make_view_cb(label, v.Id)
            )

    def _render_cats(self, filter_text):
        """Clear and rebuild the category checkbox panel, respecting the search filter."""
        ft = filter_text.strip().lower()
        self.panel_cats.Children.Clear()
        for name in ALL_CATS:
            if ft and ft not in name.lower():
                continue
            self.panel_cats.Children.Add(self._make_cat_cb(name))

    # ── Radio-toggle helpers ──────────────────────────────────────────────────
    def _radio(self, group, active):
        """Enforce single-active-item within a toggle-button group."""
        if self._lock[0]:
            return
        self._lock[0] = True
        for btn in group:
            btn.IsChecked = (btn is active)
        self._lock[0] = False

    def _guard(self, sender, e):
        """Prevent the user from unchecking the already-active radio button."""
        if not self._lock[0]:
            sender.IsChecked = True

    # ── Event handlers ────────────────────────────────────────────────────────
    def _on_action(self, sender, e):
        if not self._lock[0]:
            self._radio([self.btn_pin, self.btn_unpin], sender)

    def _on_scope(self, sender, e):
        if not self._lock[0]:
            self._radio([self.btn_cur, self.btn_sel, self.btn_proj], sender)
        self.pnl_views.Visibility = (
            Visibility.Visible if sender is self.btn_sel else Visibility.Collapsed
        )

    def _on_view_search(self, sender, e):
        self._render_views(sender.Text)

    def _on_cat_search(self, sender, e):
        self._render_cats(sender.Text)

    def _on_cat_tog(self, sender, e):
        on = bool(sender.IsChecked)
        sender.Content           = "ON"  if on else "OFF"
        self.pnl_cats.Visibility = Visibility.Visible if on else Visibility.Collapsed

    def _cancel(self, sender, e):
        self.win.Close()

    def _run(self, sender, e):
        # Determine scope
        if   self.btn_cur.IsChecked:  scope = 'current'
        elif self.btn_sel.IsChecked:  scope = 'views'
        else:                         scope = 'project'

        # Validate view selection
        sel_view_ids = [vid for vid, chk in self._view_checked.items() if chk]
        if scope == 'views' and not sel_view_ids:
            MessageBox.Show(
                "Please check at least one view.",
                "Pin / Unpin Manager",
                MessageBoxButton.OK,
                MessageBoxImage.Warning
            )
            return

        # Validate category selection
        use_cats = bool(self.btn_cat_tog.IsChecked)
        sel_cats = [n for n, chk in self._cat_checked.items() if chk]
        if use_cats and not sel_cats:
            MessageBox.Show(
                "Category filter is ON but no categories are checked.\n"
                "Please check at least one category, or turn the filter OFF.",
                "Pin / Unpin Manager",
                MessageBoxButton.OK,
                MessageBoxImage.Warning
            )
            return

        self.result = {
            'pin'      : bool(self.btn_pin.IsChecked),
            'scope'    : scope,
            'view_ids' : set(sel_view_ids),
            'use_cats' : use_cats,
            'cats'     : set(sel_cats),
        }
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.result


# ── Launch UI ─────────────────────────────────────────────────────────────────
dlg = PinUnpinDialog()
cfg = dlg.show()

if cfg is None:
    script.exit()

pin_val  = cfg['pin']
scope    = cfg['scope']
view_ids = cfg['view_ids']
use_cats = cfg['use_cats']
cats     = cfg['cats']
label    = "Pin" if pin_val else "Unpin"

# ── Element collection helpers ────────────────────────────────────────────────
def passes_cat(elem):
    """True if element passes the category filter (or filter is off)."""
    if not use_cats:
        return True
    try:
        return elem.Category is not None and elem.Category.Name in cats
    except Exception:
        return False

def elems_in_view(view_id):
    """Non-type elements visible in the given view."""
    try:
        return list(
            FilteredElementCollector(doc, view_id)
            .WhereElementIsNotElementType()
            .ToElements()
        )
    except Exception:
        return []

# ── Collect elements based on scope + category filter ────────────────────────
elements = []

if scope == 'current':
    elements = [e for e in elems_in_view(doc.ActiveView.Id) if passes_cat(e)]

elif scope == 'views':
    seen = set()
    for v in ALL_VIEWS:
        if v.Id not in view_ids:
            continue
        for e in elems_in_view(v.Id):
            eid = e.Id
            if eid not in seen:
                seen.add(eid)
                if passes_cat(e):
                    elements.append(e)

elif scope == 'project':
    if use_cats:
        # Per-BuiltInCategory collectors are fast and precise
        seen    = set()
        cat_map = {c.Name: c for c in doc.Settings.Categories}
        for cname in cats:
            cat = cat_map.get(cname)
            if cat is None:
                continue
            try:
                for e in (
                    FilteredElementCollector(doc)
                    .OfCategory(cat.BuiltInCategory)
                    .WhereElementIsNotElementType()
                    .ToElements()
                ):
                    eid = e.Id
                    if eid not in seen:
                        seen.add(eid)
                        elements.append(e)
            except Exception:
                pass
    else:
        elements = list(
            FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .ToElements()
        )

# ── Transaction ───────────────────────────────────────────────────────────────
t = Transaction(doc, "{} — Pin/Unpin Manager".format(label))
t.Start()

ok_count   = 0
skip_count = 0

for e in elements:
    try:
        e.Pinned  = pin_val
        ok_count += 1
    except Exception:
        skip_count += 1

t.Commit()

# ── Output summary ────────────────────────────────────────────────────────────
out = script.get_output()

scope_display = {
    'current': u'Current View  ({})'.format(doc.ActiveView.Name),
    'views'  : u'Selected Views  ({} views)'.format(len(view_ids)),
    'project': u'Entire Project',
}[scope]

out.print_md(u"## {} {} Complete".format(
    u"\U0001F4CC" if pin_val else u"\U0001F4CD", label
))
out.print_md(u"| | |")
out.print_md(u"|---|---|")
out.print_md(u"| **Action** | {} |".format(label))
out.print_md(u"| **Scope** | {} |".format(scope_display))
if use_cats:
    out.print_md(u"| **Categories** | {} |".format(u', '.join(sorted(cats))))
out.print_md(u"| **Processed** | {} elements |".format(ok_count))
if skip_count:
    out.print_md(u"| **Skipped** | {} (not pinnable) |".format(skip_count))