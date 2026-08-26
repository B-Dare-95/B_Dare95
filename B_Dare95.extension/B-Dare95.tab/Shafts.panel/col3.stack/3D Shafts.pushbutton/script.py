# -*- coding: utf-8 -*-

__title__   = "3D Shafts"
__doc__     = """
________________________________________________________________
Description:
- Creates Generic Models to represent Shafts in 3D Views

How to Use:
- Run the script in a 3D View
- Assign a color to each Shaft Function
- Pick a workset for the generated models
- Set transparency and click Generate
- Draw a rectangle to select Shaft Openings
________________________________________________________________
Author: Mohamed Bedair"""

# ── Imports ─────────────────────────────────────────────────────────────────
import clr
clr.AddReference('System')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System.Collections.Generic import List
import System.Windows.Forms as WinForms
import System.Drawing as Drawing

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import forms, script

# ── Revit Variables ──────────────────────────────────────────────────────────
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

# ── Guard 1 : Active view must be a 3D view ──────────────────────────────────
if not isinstance(active_view, View3D):
    forms.alert(
        "Please switch to a 3D View before running this script.",
        title="3D Shaft – Wrong View Type",
        exitscript=True
    )

# ── Guard 2 : Shaft Function parameter must exist in the project ─────────
_param_probe = (FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_ShaftOpening)
                .WhereElementIsNotElementType()
                .FirstElement())

_param_found = (_param_probe is not None and
                _param_probe.LookupParameter("Shaft Function") is not None)

if not _param_found:
    forms.alert(
        "The parameter 'Shaft Function' was not found on Shaft Openings.\n"
        "Please verify the parameter exists in this project.",
        title="3D Shaft – Missing Parameter",
        exitscript=True
    )

# ── Collect shaft data for unique function values ────────────────────────────
all_shafts = (FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_ShaftOpening)
              .WhereElementIsNotElementType()
              .ToElements())

if not all_shafts:
    forms.alert("No Shaft Openings found in the model.", exitscript=True)

unique_functions = sorted(set(
    (shaft.LookupParameter("Shaft Function").AsString() or "(Undefined)")
    for shaft in all_shafts
    if shaft.LookupParameter("Shaft Function") is not None
))

if not unique_functions:
    forms.alert("No 'Shaft Function' values found.", exitscript=True)

# ── Collect worksets ─────────────────────────────────────────────────────────
worksets = FilteredWorksetCollector(doc)\
           .OfKind(WorksetKind.UserWorkset)\
           .ToWorksets()

worksets = list(worksets)  # convert to plain Python list

if not worksets:
    forms.alert("No user worksets found in this project.", exitscript=True)

workset_names = [ws.Name for ws in worksets]

# ── 2. WinForms Dialog ───────────────────────────────────────────────────────
DEFAULT_COLORS = [
    Drawing.Color.FromArgb(100, 149, 237),
    Drawing.Color.FromArgb(255, 140,   0),
    Drawing.Color.FromArgb( 46, 204, 113),
    Drawing.Color.FromArgb(231,  76,  60),
    Drawing.Color.FromArgb(155,  89, 182),
    Drawing.Color.FromArgb(241, 196,  15),
    Drawing.Color.FromArgb(  0, 188, 212),
    Drawing.Color.FromArgb(255, 105, 180),
]

class ShaftVisualizationForm(WinForms.Form):

    C_BG     = Drawing.Color.FromArgb( 37,  37,  38)
    C_ROW    = Drawing.Color.FromArgb( 50,  50,  54)
    C_SEP    = Drawing.Color.FromArgb( 70,  70,  74)
    C_ACCENT = Drawing.Color.FromArgb(  0, 122, 204)
    C_CANCEL = Drawing.Color.FromArgb( 65,  65,  68)
    C_TEXT   = Drawing.Color.FromArgb(235, 235, 235)
    C_DIM    = Drawing.Color.FromArgb(165, 165, 165)

    PAD   = 16
    ROW_H = 46

    def __init__(self, functions, workset_names):
        WinForms.Form.__init__(self)
        self.functions      = functions
        self.workset_names  = workset_names
        self.color_map      = {f: DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
                               for i, f in enumerate(functions)}
        self.transparency   = 50
        self.workset_name   = workset_names[0] if workset_names else None
        self.confirmed      = False
        self._build_ui()

    def _build_ui(self):
        n = len(self.functions)
        W = 450
        H = (self.PAD           # top
             + 36               # header
             + n * self.ROW_H   # function rows
             + 14               # gap
             + 2                # separator
             + 12               # gap
             + 22               # workset label
             + 34               # combo box
             + 12               # gap
             + 2                # separator
             + 12               # gap
             + 20               # transparency label
             + 38               # slider
             + 20               # gap
             + 36               # buttons
             + self.PAD)        # bottom

        self.Text            = "3D Shaft Visualization"
        self.ClientSize      = Drawing.Size(W, H)
        self.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.StartPosition   = WinForms.FormStartPosition.CenterScreen
        self.BackColor       = self.C_BG

        y = self.PAD

        # Header
        self.Controls.Add(self._lbl(
            "Assign Colors to Shaft Functions",
            Drawing.Font("Segoe UI", 11, Drawing.FontStyle.Bold),
            self.PAD, y, self.C_TEXT))
        y += 36

        # Function rows
        self.color_buttons = {}
        for func in self.functions:
            panel           = WinForms.Panel()
            panel.Size      = Drawing.Size(W - self.PAD * 2, self.ROW_H - 4)
            panel.Location  = Drawing.Point(self.PAD, y)
            panel.BackColor = self.C_ROW

            swatch                              = WinForms.Button()
            swatch.Size                         = Drawing.Size(28, 28)
            swatch.Location                     = Drawing.Point(8, (panel.Height - 28) // 2)
            swatch.BackColor                    = self.color_map[func]
            swatch.FlatStyle                    = WinForms.FlatStyle.Flat
            swatch.FlatAppearance.BorderSize    = 1
            swatch.FlatAppearance.BorderColor   = Drawing.Color.FromArgb(110, 110, 110)
            swatch.Tag                          = func
            swatch.Click                       += self._on_color_click
            panel.Controls.Add(swatch)
            self.color_buttons[func] = swatch

            lbl           = WinForms.Label()
            lbl.Text      = func
            lbl.Font      = Drawing.Font("Segoe UI", 9)
            lbl.ForeColor = self.C_TEXT
            lbl.Location  = Drawing.Point(46, (panel.Height - 16) // 2)
            lbl.AutoSize  = True
            panel.Controls.Add(lbl)

            self.Controls.Add(panel)
            y += self.ROW_H

        y += 14
        y = self._sep(W, y)

        # ── Workset section ──────────────────────────────────────────────────
        self.Controls.Add(self._lbl(
            "Assign to Workset",
            Drawing.Font("Segoe UI", 9),
            self.PAD, y, self.C_DIM))
        y += 22

        self.combo_workset              = WinForms.ComboBox()
        self.combo_workset.Size         = Drawing.Size(W - self.PAD * 2, 26)
        self.combo_workset.Location     = Drawing.Point(self.PAD, y)
        self.combo_workset.DropDownStyle= WinForms.ComboBoxStyle.DropDownList
        self.combo_workset.BackColor    = self.C_ROW
        self.combo_workset.ForeColor    = self.C_TEXT
        self.combo_workset.Font         = Drawing.Font("Segoe UI", 9)
        self.combo_workset.FlatStyle    = WinForms.FlatStyle.Flat

        for name in self.workset_names:
            self.combo_workset.Items.Add(name)
        self.combo_workset.SelectedIndex = 0
        self.combo_workset.SelectedIndexChanged += self._on_workset_changed
        self.Controls.Add(self.combo_workset)
        y += 34 + 12

        y = self._sep(W, y)

        # ── Transparency section ─────────────────────────────────────────────
        self.Controls.Add(self._lbl(
            "Transparency",
            Drawing.Font("Segoe UI", 9),
            self.PAD, y + 2, self.C_DIM))

        self.lbl_pct = self._lbl(
            "50%",
            Drawing.Font("Segoe UI", 9, Drawing.FontStyle.Bold),
            W - self.PAD - 34, y + 2, self.C_TEXT)
        self.Controls.Add(self.lbl_pct)
        y += 20

        self.slider               = WinForms.TrackBar()
        self.slider.Minimum       = 0
        self.slider.Maximum       = 100
        self.slider.Value         = 50
        self.slider.TickFrequency = 10
        self.slider.Size          = Drawing.Size(W - self.PAD * 2, 34)
        self.slider.Location      = Drawing.Point(self.PAD, y)
        self.slider.BackColor     = self.C_BG
        self.slider.ValueChanged += self._on_slider_changed
        self.Controls.Add(self.slider)
        y += 52

        # ── Buttons ──────────────────────────────────────────────────────────
        BTN_W, BTN_H = 110, 32

        btn_gen              = WinForms.Button()
        btn_gen.Text         = "Generate"
        btn_gen.Size         = Drawing.Size(BTN_W, BTN_H)
        btn_gen.Location     = Drawing.Point(W - self.PAD - BTN_W * 2 - 8, y)
        btn_gen.FlatStyle    = WinForms.FlatStyle.Flat
        btn_gen.BackColor    = self.C_ACCENT
        btn_gen.ForeColor    = Drawing.Color.White
        btn_gen.Font         = Drawing.Font("Segoe UI", 9, Drawing.FontStyle.Bold)
        btn_gen.FlatAppearance.BorderSize = 0
        btn_gen.Click       += self._on_ok
        self.Controls.Add(btn_gen)

        btn_cancel           = WinForms.Button()
        btn_cancel.Text      = "Cancel"
        btn_cancel.Size      = Drawing.Size(BTN_W, BTN_H)
        btn_cancel.Location  = Drawing.Point(W - self.PAD - BTN_W, y)
        btn_cancel.FlatStyle = WinForms.FlatStyle.Flat
        btn_cancel.BackColor = self.C_CANCEL
        btn_cancel.ForeColor = self.C_TEXT
        btn_cancel.Font      = Drawing.Font("Segoe UI", 9)
        btn_cancel.FlatAppearance.BorderSize = 0
        btn_cancel.Click    += self._on_cancel
        self.Controls.Add(btn_cancel)

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _lbl(self, text, font, x, y, color):
        l           = WinForms.Label()
        l.Text      = text
        l.Font      = font
        l.ForeColor = color
        l.Location  = Drawing.Point(x, y)
        l.AutoSize  = True
        return l

    def _sep(self, W, y):
        sep           = WinForms.Label()
        sep.Size      = Drawing.Size(W - self.PAD * 2, 1)
        sep.Location  = Drawing.Point(self.PAD, y)
        sep.BackColor = self.C_SEP
        self.Controls.Add(sep)
        return y + 2 + 12   # separator height + gap below

    # ── Event Handlers ────────────────────────────────────────────────────────
    def _on_color_click(self, sender, e):
        func      = sender.Tag
        dlg       = WinForms.ColorDialog()
        dlg.Color = self.color_map[func]
        dlg.FullOpen = True
        if dlg.ShowDialog() == WinForms.DialogResult.OK:
            self.color_map[func] = dlg.Color
            sender.BackColor     = dlg.Color

    def _on_workset_changed(self, sender, e):
        self.workset_name = self.combo_workset.SelectedItem

    def _on_slider_changed(self, sender, e):
        self.transparency = self.slider.Value
        self.lbl_pct.Text = "{}%".format(self.transparency)

    def _on_ok(self, sender, e):
        self.confirmed = True
        self.Close()

    def _on_cancel(self, sender, e):
        self.Close()

# ── Show Dialog ──────────────────────────────────────────────────────────────
WinForms.Application.EnableVisualStyles()
form = ShaftVisualizationForm(unique_functions, workset_names)
form.ShowDialog()

if not form.confirmed:
    script.exit()

color_map        = form.color_map       # {function_str : Drawing.Color}
transparency     = form.transparency    # int 0-100
chosen_workset   = next(ws for ws in worksets
                        if ws.Name == form.workset_name)

# ── 3. ISelectionFilter – Shaft Openings only ────────────────────────────────
class ShaftSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return element.Category is not None and \
               element.Category.Id == ElementId(BuiltInCategory.OST_ShaftOpening)

    def AllowReference(self, reference, point):
        return False

# ── 4. Pick by Rectangle ─────────────────────────────────────────────────────
try:
    picked = selection.PickElementsByRectangle(
        ShaftSelectionFilter(),
        "Draw a rectangle to select Shaft Openings"
    )
except Exception:
    # User pressed ESC or cancelled
    script.exit()

if not picked:
    forms.alert("No Shaft Openings were selected. Exiting.", exitscript=True)

# ── 5. Build shaft_data only from picked elements ────────────────────────────
shaft_data = []
for shaft in picked:
    func_param  = shaft.LookupParameter("Shaft Function")
    func        = func_param.AsString() if func_param and func_param.AsString() else "(Undefined)"

    base_level_id = shaft.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
    base_level    = doc.GetElement(base_level_id)
    base_elev     = base_level.Elevation if base_level else 0.0
    base_offset   = shaft.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).AsDouble()

    shaft_data.append({
        'element' : shaft,
        'bounds'  : shaft.BoundaryCurves,
        'height'  : shaft.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble(),
        'function': func,
        'z_start' : base_elev + base_offset,
    })

# ── Geometry & Override Helpers ───────────────────────────────────────────
def get_solid_fill_id(doc):
    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
        if fp.GetFillPattern().IsSolidFill:
            return fp.Id
    return ElementId.InvalidElementId

def win_to_revit_color(c):
    return Color(c.R, c.G, c.B)

def split_closed_curve(curve):
    """
    Split a single closed curve into two halves so CurveLoop accepts it.
    Handles Arc (circles) and Ellipse. Falls back to tessellated lines for
    any other closed curve type.
    """
    p0   = curve.GetEndParameter(0)
    p1   = curve.GetEndParameter(1)
    pmid = (p0 + p1) / 2.0

    if isinstance(curve, Arc):
        c1 = Arc.Create(curve.Center, curve.Radius,
                        p0, pmid, curve.XDirection, curve.YDirection)
        c2 = Arc.Create(curve.Center, curve.Radius,
                        pmid, p1, curve.XDirection, curve.YDirection)
        return [c1, c2]

    if isinstance(curve, Ellipse):
        c1 = Ellipse.CreateCurve(curve.Center,
                                  curve.RadiusX, curve.RadiusY,
                                  curve.XDirection, curve.YDirection,
                                  p0, pmid)
        c2 = Ellipse.CreateCurve(curve.Center,
                                  curve.RadiusX, curve.RadiusY,
                                  curve.XDirection, curve.YDirection,
                                  pmid, p1)
        return [c1, c2]

    # Generic fallback: tessellate into line segments
    pts  = list(curve.Tessellate())
    mid  = len(pts) // 2
    segs = []
    for i in range(len(pts) - 1):
        segs.append(Line.CreateBound(pts[i], pts[i + 1]))
    return segs

def chain_curves(curves):
    """
    Sort curves into a single continuous end-to-end chain.
    Reverses individual curves as needed.
    Raises if a continuous loop cannot be formed.
    """
    TOL      = 1e-6
    ordered  = [curves[0]]
    remaining = list(curves[1:])

    while remaining:
        tail  = ordered[-1].GetEndPoint(1)
        found = False
        for i, c in enumerate(remaining):
            if tail.DistanceTo(c.GetEndPoint(0)) < TOL:
                ordered.append(remaining.pop(i))
                found = True
                break
            elif tail.DistanceTo(c.GetEndPoint(1)) < TOL:
                ordered.append(c.CreateReversed())
                remaining.pop(i)
                found = True
                break
        if not found:
            raise Exception(
                "Cannot form a continuous loop — gap of {:.6f} ft at curve junction."
                .format(min(tail.DistanceTo(c.GetEndPoint(0)) for c in remaining))
            )
    return ordered

def build_solid(info):
    curves = list(info['bounds'])

    # ── Fix: single closed curve (e.g. circular shaft) ───────────────────
    if len(curves) == 1:
        curves = split_closed_curve(curves[0])

    # ── Fix: sort into continuous chain ──────────────────────────────────
    curves = chain_curves(curves)

    loop = CurveLoop()
    for c in curves:
        loop.Append(c)

    profile = List[CurveLoop]()
    profile.Add(loop)

    return GeometryCreationUtilities.CreateExtrusionGeometry(
        profile, XYZ.BasisZ, info['height'])

# ── 7. Create DirectShapes + Assign Workset + Apply Overrides ────────────────
solid_fill_id  = get_solid_fill_id(doc)
gm_category    = ElementId(BuiltInCategory.OST_GenericModel)
workset_param  = BuiltInParameter.ELEM_PARTITION_PARAM
created        = 0
skipped        = 0

with Transaction(doc, "3D Shaft – Create DirectShapes") as t:
    t.Start()

    for info in shaft_data:
        func = info['function']

        try:
            solid = build_solid(info)
        except Exception as ex:
            output.print_md("⚠ **Shaft {}** skipped — geometry error: `{}`"
                            .format(info['element'].Id, ex))
            skipped += 1
            continue

        geom_list = List[GeometryObject]()
        geom_list.Add(solid)

        ds = DirectShape.CreateElement(doc, gm_category)
        ds.SetShape(geom_list)

        # Assign workset
        ws_param = ds.get_Parameter(workset_param)
        if ws_param and not ws_param.IsReadOnly:
            ws_param.Set(chosen_workset.Id.IntegerValue)

        # Build and apply graphical override
        win_color   = color_map.get(func, Drawing.Color.Gray)
        revit_color = win_to_revit_color(win_color)

        ogs = OverrideGraphicSettings()
        ogs.SetSurfaceForegroundPatternId(solid_fill_id)
        ogs.SetSurfaceForegroundPatternColor(revit_color)
        ogs.SetSurfaceForegroundPatternVisible(True)
        ogs.SetSurfaceTransparency(transparency)

        active_view.SetElementOverrides(ds.Id, ogs)
        created += 1

    t.Commit()

output.print_md("✅ **Done** — {} DirectShape(s) created, {} skipped.".format(created, skipped))