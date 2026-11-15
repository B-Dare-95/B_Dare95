# -*- coding: utf-8 -*-
TOOL_NAME   = "Room Numbering"
__author__  = "B-Dare95"
__version__ = "Version 3.0"
__doc__ = """__________________________________________________
Description:

Renumbers all placed rooms level by level, starting from the room nearest a grid corner you choose and moving outwards.
Add a prefix or suffix, and choose whether numbering restarts on each level, runs through the whole project, or covers one level only.
__________________________________________________
How-to:

-> Click on the button
-> Pick the room parameter to fill (usually Number)
-> Click one of the four grid corners as the starting point
-> Set the prefix, suffix and start number
-> Choose Per Level, Full Project or One Level (then pick the level from the list), and click RUN
-> A summary per level shows when it's done
__________________________________________________
Author: Mohamed Bedair"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
# ==================================================
import math

from Autodesk.Revit.DB import (
    BuiltInCategory,
    FilteredElementCollector,
    Grid,
    StorageType,
    Transaction,
)


import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")

from System.Windows import Visibility
from bd_combo_search import enable_combo_search
import bd_core as bd

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
# ==================================================
doc      = __revit__.ActiveUIDocument.Document   # noqa: F821
uidoc    = __revit__.ActiveUIDocument            # noqa: F821
app      = __revit__.Application                 # noqa: F821
rvt_year = int(app.VersionNumber)

# ╔╦╗╦═╗╔═╗╔╗╔╔═╗╔═╗╔═╗╔╦╗╦╔═╗╔╗╔
#  ║ ╠╦╝╠═╣║║║╚═╗╠═╣║   ║ ║║ ║║║║
#  ╩ ╩╚═╩ ╩╝╚╝╚═╝╩ ╩╚═╝ ╩ ╩╚═╝╝╚╝
# ==================================================
try:
    from Snippets._context_manager import ef_Transaction
    _HAS_EF = True
except Exception:
    _HAS_EF = False


class _SimpleTx(object):
    def __init__(self, doc, name):
        self._t = Transaction(doc, name)

    def __enter__(self):
        self._t.Start()
        return self._t

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._t.HasStarted():
            self._t.RollBack() if exc_type else self._t.Commit()
        return False


def _make_tx(doc, name):
    return ef_Transaction(doc, name, debug=True) if _HAS_EF else _SimpleTx(doc, name)


# ╔═╗╦═╗╦╔╦╗  ╔═╗╔╗╔╔═╗╦  ╦╔═╗╦╔═╗
# ║ ╦╠╦╝║ ║║  ╠═╣║║║╠═╣║  ╚╗╔╝╚═╗║╚═╗
# ╚═╝╩╚═╩═╩╝  ╩ ╩╝╚╝╩ ╩╩═╝ ╚╝ ╚═╝╩╚═╝
# ==================================================

_DEDUP_TOL = 0.01   # ft — merge near-identical intersection points


def _intersect_2d(x1, y1, dx1, dy1, x2, y2, dx2, dy2):
    """Analytical 2-D intersection of two infinite lines. Returns (x,y) or None."""
    cross = dx1 * dy2 - dy1 * dx2
    if abs(cross) < 1e-9:
        return None
    t = ((x2 - x1) * dy2 - (y2 - y1) * dx2) / cross
    return (x1 + t * dx1, y1 + t * dy1)


def analyse_grids(doc):
    """
    Compute all pairwise Grid-Line intersections and identify the four
    corner points of the intersection bounding box.

    Returns dict or None (when < 2 grids / no intersections).
    """
    grids = list(FilteredElementCollector(doc).OfClass(Grid).ToElements())
    if len(grids) < 2:
        return None

    lines = []
    for g in grids:
        try:
            crv = g.Curve
            s   = crv.GetEndPoint(0)
            e   = crv.GetEndPoint(1)
            dx  = e.X - s.X
            dy  = e.Y - s.Y
            ln  = math.sqrt(dx * dx + dy * dy)
            if ln < 1e-9:
                continue
            lines.append((s.X, s.Y, dx / ln, dy / ln))
        except Exception:
            pass

    if len(lines) < 2:
        return None

    raw_pts = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            pt = _intersect_2d(*(lines[i] + lines[j]))
            if pt is not None:
                raw_pts.append(pt)

    if not raw_pts:
        return None

    unique_pts = []
    for p in raw_pts:
        is_dup = False
        for u in unique_pts:
            if abs(p[0] - u[0]) < _DEDUP_TOL and abs(p[1] - u[1]) < _DEDUP_TOL:
                is_dup = True
                break
        if not is_dup:
            unique_pts.append(p)

    if not unique_pts:
        return None

    min_x = min(p[0] for p in unique_pts)
    max_x = max(p[0] for p in unique_pts)
    min_y = min(p[1] for p in unique_pts)
    max_y = max(p[1] for p in unique_pts)

    def _nearest(tx, ty):
        return min(unique_pts, key=lambda p: (p[0] - tx) ** 2 + (p[1] - ty) ** 2)

    return {
        'grid_count':    len(grids),
        'intersections': unique_pts,
        'corners': {
            'TL': _nearest(min_x, max_y),
            'TR': _nearest(max_x, max_y),
            'BL': _nearest(min_x, min_y),
            'BR': _nearest(max_x, min_y),
        },
    }


# ╦═╗╔═╗╔═╗╔╦╗╔═╗  ╦ ╦╔╦╗╦╦  ╦╔╦╗╦╔═╗╔═╗
# ╠╦╝║ ║║ ║║║║╚═╗  ║ ║ ║ ║║  ║ ║ ║║╣ ╚═╗
# ╩╚═╚═╝╚═╝╩ ╩╚═╝  ╚═╝ ╩ ╩╩═╝╩ ╩ ╩╚═╝╚═╝
# ==================================================

def get_placed_rooms(doc):
    all_rooms = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_Rooms)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    placed = []
    for r in all_rooms:
        try:
            if r.Area > 0 and r.Location is not None:
                placed.append(r)
        except Exception:
            pass
    return placed


def get_room_xy(room):
    try:
        loc = room.Location
        if loc and hasattr(loc, 'Point') and loc.Point:
            return (loc.Point.X, loc.Point.Y)
    except Exception:
        pass
    return None


def collect_room_writable_params(rooms):
    """
    Return a sorted list of (name, StorageType) for every writable
    String OR Integer parameter found across all supplied rooms.

    Integer parameters require numeric Prefix/Suffix — the UI
    enforces this constraint at runtime.
    """
    seen = {}   # name → StorageType  (first-seen wins on name collision)
    for room in rooms:
        try:
            for param in room.Parameters:
                n  = param.Definition.Name
                st = param.StorageType
                if n not in seen and not param.IsReadOnly:
                    if st == StorageType.String or st == StorageType.Integer:
                        seen[n] = st
        except Exception:
            pass
    return sorted(seen.items(), key=lambda t: t[0])   # [(name, StorageType)]


def group_rooms_by_level(rooms, doc):
    """
    Partition placed rooms by Level, sorted by elevation ascending.
    Returns list of {'name', 'elevation', 'rooms'}.
    """
    groups   = {}
    no_level = []

    for room in rooms:
        try:
            lvl_id = room.LevelId
            if lvl_id is None:
                no_level.append(room)
                continue
            lvl = doc.GetElement(lvl_id)
            if lvl is None:
                no_level.append(room)
                continue

            try:
                key = int(lvl_id.Value)
            except AttributeError:
                key = int(lvl_id.IntegerValue)

            if key not in groups:
                groups[key] = {'name': lvl.Name, 'elevation': lvl.Elevation, 'rooms': [],
                               'key': key}
            groups[key]['rooms'].append(room)
        except Exception:
            no_level.append(room)

    result = sorted(groups.values(), key=lambda g: g['elevation'])
    if no_level:
        result.append({'name': '(No Level)', 'elevation': 1e18, 'rooms': no_level,
                       'key': None})
    return result


def sort_by_distance(rooms, ref_pt):
    """Sort rooms by Euclidean distance from ref_pt, nearest first."""
    rx, ry = ref_pt[0], ref_pt[1]

    def _dist(room):
        c = get_room_xy(room)
        if c is None:
            return 1e18
        return math.sqrt((c[0] - rx) ** 2 + (c[1] - ry) ** 2)

    return sorted(rooms, key=_dist)


# ╔═╗╦  ╦ ╦╦   ╦ ╦╦
# ║ ╦║  ║ ║║   ║ ║║
# ╚═╝╩═╝╚═╝╩   ╚═╝╩
# ==================================================

_CORNER_BTN_NAMES   = {'TL': 'UI_corner_tl', 'TR': 'UI_corner_tr',
                       'BL': 'UI_corner_bl', 'BR': 'UI_corner_br'}
_CORNER_COORD_NAMES = {'TL': 'UI_coord_tl',  'TR': 'UI_coord_tr',
                       'BL': 'UI_coord_bl',  'BR': 'UI_coord_br'}
_CORNER_LABELS      = {'TL': 'TOP-LEFT',     'TR': 'TOP-RIGHT',
                       'BL': 'BOT-LEFT',     'BR': 'BOT-RIGHT'}

# Window layout: ui.xaml next to this script (shared colours and styles: lib/bd_theme.xaml)


# ╔═╗╦  ╦ ╦╦   ╔═╗╦  ╔═╗╔═╗╔═╗
# ║ ╦║  ║ ║║   ║  ║  ╠═╣╚═╗╚═╗
# ╚═╝╩═╝╚═╝╩   ╚═╝╩═╝╩ ╩╚═╝╚═╝
# ==================================================

class RoomGridUI(object):
    """
    WPF dialog — v3.0.

    Left panel  : parameter list (TEXT · INT badges)
                  + inline error banner for Integer-type violations
    Right panel : 2×2 corner tile grid
                  + Prefix / Suffix / Start Number / Sequence Mode

    IronPython 2.7 — all output in mutable list containers (no nonlocal).
    """

    def __init__(self, params, grid_info, level_groups):
        """
        params       : list of (name, StorageType)
        grid_info    : dict from analyse_grids()
        level_groups : list from group_rooms_by_level()
        """
        self._params       = params          # [(name, StorageType)]
        self._grid_info    = grid_info
        self._level_groups = level_groups
        self._param_data   = []              # parallel to ListBox items

        # ── Output state ──────────────────────────────────────────────
        self.confirmed      = [False]
        self.param_name     = [None]
        self.p_storage_type = [None]         # StorageType.String / .Integer
        self.corner_key     = [None]         # 'TL' / 'TR' / 'BL' / 'BR'
        self.prefix         = ['']
        self.suffix         = ['']
        self.start          = [1]
        self.per_level      = [True]         # True = reset each level
        self.single_level   = [None]         # level group dict when One Level is chosen

        # ── Build window ─────────────────────────────────────────────
        self._win = bd.load_window(__file__)

        # ── Resolve controls ─────────────────────────────────────────
        self._param_list    = self._win.FindName('UI_param_list')
        self._param_hint    = self._win.FindName('UI_param_hint')
        self._error_border  = self._win.FindName('UI_error_border')
        self._error_msg     = self._win.FindName('UI_error_msg')
        self._prefix_tb     = self._win.FindName('UI_prefix')
        self._suffix_tb     = self._win.FindName('UI_suffix')
        self._start_tb      = self._win.FindName('UI_start')
        self._status_lbl    = self._win.FindName('UI_status')
        self._ver_lbl       = self._win.FindName('UI_version')
        self._seq_level_btn = self._win.FindName('UI_seq_level')
        self._seq_proj_btn  = self._win.FindName('UI_seq_project')
        self._seq_one_btn   = self._win.FindName('UI_seq_single')
        self._level_row     = self._win.FindName('UI_level_row')
        self._level_combo   = self._win.FindName('UI_level_combo')
        self._btn_run       = self._win.FindName('UI_run')
        self._btn_cancel    = self._win.FindName('UI_cancel')

        self._corner_btns = {
            k: self._win.FindName(v)
            for k, v in _CORNER_BTN_NAMES.items()
        }

        # ── Populate ─────────────────────────────────────────────────
        if self._ver_lbl:
            self._ver_lbl.Text = __version__
        self._fill_param_list()
        self._fill_corner_coords()
        self._fill_level_combo()
        self._fill_status()

        # ── Wire events ───────────────────────────────────────────────
        self._param_list.SelectionChanged += self._on_param_selected
        self._btn_run.Click               += self._on_run
        self._btn_cancel.Click            += self._on_cancel
        for btn in (self._seq_level_btn, self._seq_proj_btn, self._seq_one_btn):
            btn.Checked += self._on_mode_changed
        self._level_combo.SelectionChanged += self._on_level_selected

        enable_combo_search(self._win)
        self._win.ShowDialog()

    # ── Populate helpers ──────────────────────────────────────────────

    def _fill_param_list(self):
        """
        Populate the parameter ListBox.
        Each item is displayed as  "Name   ·   TEXT"  or  "Name   ·   INT"
        so the user immediately knows which type they are choosing.
        The parallel _param_data list provides the raw (name, StorageType).
        """
        self._param_list.Items.Clear()
        self._param_data = []

        if self._params:
            for name, st in self._params:
                type_tag = u'TEXT' if st == StorageType.String else u'INT'
                display  = u'{}   \u00b7   {}'.format(name, type_tag)
                self._param_list.Items.Add(display)
                self._param_data.append((name, st))
        else:
            self._param_list.Items.Add(
                u'\u2014 no writable parameters found \u2014'
            )

    def _fill_corner_coords(self):
        for key, coord_ctrl_name in _CORNER_COORD_NAMES.items():
            lbl = self._win.FindName(coord_ctrl_name)
            if lbl and key in self._grid_info['corners']:
                pt = self._grid_info['corners'][key]
                lbl.Text = u'X={:.2f}   Y={:.2f}'.format(pt[0], pt[1])

    def _fill_level_combo(self):
        """
        One entry per level that has placed rooms, lowest first, shown as
        "Level name   ·   N rooms". The active view's level is preselected
        when it has rooms, otherwise the first level.
        """
        self._level_combo.Items.Clear()
        for g in self._level_groups:
            n = len(g['rooms'])
            self._level_combo.Items.Add(
                u'{}   \u00b7   {} room{}'.format(g['name'], n, 's' if n != 1 else '')
            )

        active_key = None
        try:
            lvl = doc.ActiveView.GenLevel
            if lvl is not None:
                try:
                    active_key = int(lvl.Id.Value)
                except AttributeError:
                    active_key = int(lvl.Id.IntegerValue)
        except Exception:
            active_key = None

        start_idx = 0
        for i, g in enumerate(self._level_groups):
            if active_key is not None and g.get('key') == active_key:
                start_idx = i
                break
        if self._level_groups:
            self._level_combo.SelectedIndex = start_idx

    def _is_single_mode(self):
        return self._seq_one_btn is not None and self._seq_one_btn.IsChecked == True  # noqa: E712

    def _fill_status(self):
        groups = self._level_groups
        if self._is_single_mode():
            idx = self._level_combo.SelectedIndex
            groups = [self._level_groups[idx]] if 0 <= idx < len(self._level_groups) else []
        n_levels = len(groups)
        n_rooms  = sum(len(g['rooms']) for g in groups)
        if self._status_lbl:
            self._status_lbl.Text = (
                u'{} level{}   \u00b7   {} room{}'.format(
                    n_levels, 's' if n_levels != 1 else '',
                    n_rooms,  's' if n_rooms  != 1 else '',
                )
            )

    def _clear_error(self):
        """Hide the inline error banner."""
        if self._error_border:
            self._error_border.Visibility = Visibility.Collapsed
        if self._error_msg:
            self._error_msg.Text = ''

    def _show_error(self, msg):
        """Display an inline error banner in the left panel."""
        if self._error_msg:
            self._error_msg.Text = msg
        if self._error_border:
            self._error_border.Visibility = Visibility.Visible

    # ── Event handlers ────────────────────────────────────────────────

    def _on_param_selected(self, sender, e):
        """Update the type hint and clear any active error on selection change."""
        self._clear_error()
        idx = self._param_list.SelectedIndex
        if 0 <= idx < len(self._param_data):
            name, st = self._param_data[idx]
            if st == StorageType.String:
                hint = u'\u2714  {}   \u00b7   TEXT \u2014 accepts any string'.format(name)
            else:
                hint = u'\u2714  {}   \u00b7   INT \u2014 digits only'.format(name)
            if self._param_hint:
                self._param_hint.Text = hint

    def _on_mode_changed(self, sender, e):
        """Show the level picker only for One Level, and refresh the status line."""
        if self._level_row is not None:
            self._level_row.Visibility = (
                Visibility.Visible if self._is_single_mode() else Visibility.Collapsed
            )
        self._fill_status()

    def _on_level_selected(self, sender, e):
        self._fill_status()

    def _on_run(self, sender, e):
        """Validate all inputs; show inline error for Integer violations; commit."""
        # ── Parameter ────────────────────────────────────────────────
        idx = self._param_list.SelectedIndex
        if idx < 0 or not self._param_data:
            bd.alert('Please select a Room Parameter.', TOOL_NAME)
            return
        actual_name, storage_type = self._param_data[idx]

        # ── Corner ───────────────────────────────────────────────────
        chosen_key = None
        for key, btn in self._corner_btns.items():
            if btn is not None and btn.IsChecked == True:   # noqa: E712
                chosen_key = key
                break
        if chosen_key is None:
            bd.alert(
                'Please select a Reference Corner\n'
                '(click one of the four arrow tiles).',
                TOOL_NAME)
            return

        # ── Start Number ─────────────────────────────────────────────
        try:
            start = int(self._start_tb.Text.strip())
        except (ValueError, AttributeError):
            bd.alert('Start Number must be a whole number (e.g. 1).', TOOL_NAME)
            return

        pfx = self._prefix_tb.Text or ''
        sfx = self._suffix_tb.Text or ''

        # ── Integer-type constraint check ─────────────────────────────
        # The composed value  Prefix + Number + Suffix  must be parseable
        # as a Python int so it can be passed to Revit's param.Set(int).
        if storage_type == StorageType.Integer:
            test_val = pfx + str(start) + sfx
            try:
                int(test_val)
            except ValueError:
                self._show_error(
                    u'\u26A0  INTEGER parameter selected.\n'
                    u'Prefix + Number + Suffix must together form a whole number '
                    u'(e.g. "10", "101", "5").  Remove any letters, spaces, or '
                    u'symbols from Prefix and Suffix, or choose a TEXT parameter.'
                )
                return

        # ── One Level needs a level ───────────────────────────────────
        single_group = None
        if self._is_single_mode():
            lvl_idx = self._level_combo.SelectedIndex
            if not (0 <= lvl_idx < len(self._level_groups)):
                bd.alert('Please pick the level to renumber.', TOOL_NAME)
                return
            single_group = self._level_groups[lvl_idx]

        # ── All valid — clear error and commit ────────────────────────
        self._clear_error()

        self.confirmed[0]      = True
        self.param_name[0]     = actual_name
        self.p_storage_type[0] = storage_type
        self.corner_key[0]     = chosen_key
        self.prefix[0]         = pfx
        self.suffix[0]         = sfx
        self.start[0]          = start
        self.per_level[0]      = (self._seq_level_btn.IsChecked == True)  # noqa: E712
        self.single_level[0]   = single_group
        self._win.Close()

    def _on_cancel(self, sender, e):
        self._win.Close()


# ╔╦╗╔═╗╦╔╗╔  ╔═╗═╗ ╦╔═╗╔═╗╦ ╦╔╦╗╦╔═╗╔╗╔
# ║║║╠═╣║║║║  ║╣ ╔╩╦╝║╣ ║  ║ ║ ║ ║║ ║║║║
# ╩ ╩╩ ╩╩╝╚╝  ╚═╝╩ ╚═╚═╝╚═╝╚═╝ ╩ ╩╚═╝╝╚╝
# ==================================================

# ── Step 1: Grid analysis ─────────────────────────────────────────────────
grid_info = analyse_grids(doc)

if grid_info is None:
    bd.alert(
        'Insufficient Grid Lines detected.\n\n'
        'At least 2 non-parallel Grid Lines are required to compute\n'
        'intersection points.  Please add grids and try again.',
        TOOL_NAME,
        exit=True)

# ── Step 2: Rooms + parameters + levels ──────────────────────────────────
placed_rooms = get_placed_rooms(doc)

if not placed_rooms:
    bd.alert(
        'No placed Rooms found in the project.\n'
        'Please place Rooms before running this script.',
        TOOL_NAME,
        exit=True)

room_params  = collect_room_writable_params(placed_rooms)
level_groups = group_rooms_by_level(placed_rooms, doc)

if not level_groups:
    bd.alert(
        'Could not resolve a Level for any placed Room.',
        TOOL_NAME,
        exit=True)

# ── Step 3: Launch UI ─────────────────────────────────────────────────────
ui = RoomGridUI(room_params, grid_info, level_groups)

if not ui.confirmed[0]:
    bd.alert('Cancelled.', TOOL_NAME, exit=True)

p_name      = ui.param_name[0]
p_storage   = ui.p_storage_type[0]
ref_pt      = grid_info['corners'][ui.corner_key[0]]
prefix      = ui.prefix[0]
suffix      = ui.suffix[0]
start_count = ui.start[0]
per_level   = ui.per_level[0]
single_grp  = ui.single_level[0]

# One Level behaves like Per Level, applied to the chosen level only.
if single_grp is not None:
    per_level  = True
    run_groups = [single_grp]
else:
    run_groups = level_groups

corner_label = _CORNER_LABELS.get(ui.corner_key[0], ui.corner_key[0])
if single_grp is not None:
    seq_label = u'One Level  ({})'.format(single_grp['name'])
else:
    seq_label = u'Per Level' if per_level else u'Full Project'

# ── Zero-padding width ────────────────────────────────────────────────────
# Applies to TEXT parameters only (integers cannot carry leading zeros).
# Full Project : fixed once, based on total rooms across every level.
# Per Level    : recomputed inside the loop for each level individually.
if p_storage == StorageType.String and not per_level:
    _total_rooms = sum(len(g['rooms']) for g in level_groups)
    pad_width    = len(str(_total_rooms))
else:
    pad_width = 1   # per-level overrides below; Integer never reads this

# ── Step 4: Renumber ──────────────────────────────────────────────────────
# Single transaction covers all levels — one atomic undo step.
level_summaries = []
total_numbered  = 0
total_skipped   = 0
count           = start_count   # running counter across levels

with _make_tx(doc, TOOL_NAME):
    for group in run_groups:
        if per_level:
            count = start_count
            if p_storage == StorageType.String:  # per-level pad
                pad_width = len(str(len(group['rooms'])))

        level_rooms  = sort_by_distance(group['rooms'], ref_pt)
        lvl_start    = count
        lvl_numbered = 0

        for room in level_rooms:
            param = room.LookupParameter(p_name)
            if param and not param.IsReadOnly:
                try:
                    if p_storage == StorageType.String:
                        param.Set(prefix + str(count).zfill(pad_width) + suffix)
                    else:                                   # StorageType.Integer
                        param.Set(int(prefix + str(count) + suffix))
                    count        += 1
                    lvl_numbered += 1
                except Exception:
                    total_skipped += 1
            else:
                total_skipped += 1

        total_numbered += lvl_numbered
        level_summaries.append((
            group['name'],
            lvl_numbered,
            lvl_start,
            count - 1,
            pad_width if p_storage == StorageType.String else 0,
        ))

# ── Step 5: Summary ───────────────────────────────────────────────────────
level_lines = u'\n'.join(
    u'  {name:<22} {n} room{pl}   '
    u'({pfx}{s}{sfx} \u2013 {pfx}{e}{sfx})'.format(
        name = name,
        n    = n,
        pl   = 's' if n != 1 else ' ',
        pfx  = prefix,
        sfx  = suffix,
        s    = str(s).zfill(pw) if pw > 0 else str(s),
        e    = str(e).zfill(pw) if pw > 0 else str(e),
    )
    for name, n, s, e, pw in level_summaries
)

bd.alert(
    u'Renumbering complete!\n\n'
    u'Parameter    : {param}  [{ptype}]\n'
    u'Reference    : {corner}  (X={rx:.2f}   Y={ry:.2f})\n'
    u'Sequence     : {seq}\n\n'
    u'Per-level breakdown:\n{levels}\n\n'
    u'{total} room{tpl} numbered   \u00b7   {sk} skipped.'.format(
        param  = p_name,
        ptype  = u'TEXT' if p_storage == StorageType.String else u'INT',
        corner = corner_label,
        rx     = ref_pt[0],
        ry     = ref_pt[1],
        seq    = seq_label,
        levels = level_lines,
        total  = total_numbered,
        tpl    = u's' if total_numbered != 1 else u'',
        sk     = total_skipped,
    ),
    TOOL_NAME)
# ==================================================