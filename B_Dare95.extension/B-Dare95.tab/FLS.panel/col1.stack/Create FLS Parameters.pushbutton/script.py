# -*- coding: utf-8 -*-
"""
FLS Parameter Creator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Creates four project parameters in the active Revit document:

  1.  FLS Occupancy           – free-text occupancy description
  2.  FLS Area Measurement    – "NET", "GROSS", or "N.O.SEATS"
  3.  FLS Occupancy Factor    – load factor value (m²/person)
  4.  FLS Function of Space   – key parameter for Room Key Schedule
                                (linked to Table 1004.5 entries)

All parameters share identical settings:
  Category   : Rooms (only)
  Discipline : Common
  Data Type  : Text
  Parameter  : Instance
  Group      : Identity Data
  Varies by  : Group Instance  → Yes

A confirmation dialog is shown before any change is made.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Author  : B_Dare95
Version : 1.2.0
"""

# ──────────────────────────────────────────────────────────────
# IMPORTS
# ──────────────────────────────────────────────────────────────
import clr
import os, tempfile

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

# ── IronPython 2.7 rule: NEVER do "from System.Windows.Forms import <EnumName>"
# WinForms enums are NOT importable as top-level names.
# Always access them as  WinForms.<ClassName>.<Member>
import System.Windows.Forms as WinForms
import System.Drawing       as Drawing

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    Transaction,
    BuiltInCategory,
    ExternalDefinitionCreationOptions,
    CategorySet,
    SharedParameterElement,
)

from pyrevit import script

# ──────────────────────────────────────────────────────────────
# BACKWARDS-COMPATIBLE PARAMETER GROUP
# ──────────────────────────────────────────────────────────────
# Revit 2024+ removed BuiltInParameterGroup entirely.
# GroupTypeId.IdentityData is the modern replacement.
try:
    from Autodesk.Revit.DB import GroupTypeId
    IDENTITY_DATA_GROUP = GroupTypeId.IdentityData
except Exception:
    from Autodesk.Revit.DB import BuiltInParameterGroup
    IDENTITY_DATA_GROUP = BuiltInParameterGroup.PG_IDENTITY_DATA

# ──────────────────────────────────────────────────────────────
# REVIT HANDLES
# ──────────────────────────────────────────────────────────────
app = __revit__.Application
doc = __revit__.ActiveUIDocument.Document

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# (name, dialog_data_type_label, is_number)
# ──────────────────────────────────────────────────────────────
PARAM_DEFS = [
    ("FLS Occupancy",         "Text",   False),
    ("FLS Area Measurement",  "Text",   False),
    ("FLS Occupancy Factor",  "Number", True),
    ("FLS Function of Space", "Text",   False),
]
PARAM_NAMES = [p[0] for p in PARAM_DEFS]  # kept for skip-check loop


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 1 – THEME CONSTANTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLR_BG         = Drawing.Color.FromArgb(45, 45, 48)
CLR_PANEL      = Drawing.Color.FromArgb(37, 37, 38)
CLR_HEADER     = Drawing.Color.FromArgb(0, 122, 204)
CLR_ROW_A      = Drawing.Color.FromArgb(55, 55, 58)
CLR_ROW_B      = Drawing.Color.FromArgb(45, 45, 48)
CLR_BORDER     = Drawing.Color.FromArgb(80, 80, 83)
CLR_TEXT       = Drawing.Color.FromArgb(241, 241, 241)
CLR_MUTED      = Drawing.Color.FromArgb(160, 160, 165)
CLR_OK_BG      = Drawing.Color.FromArgb(0, 122, 204)
CLR_OK_HOVER   = Drawing.Color.FromArgb(28, 151, 234)
CLR_CANCEL_BG  = Drawing.Color.FromArgb(62, 62, 66)
CLR_CANCEL_HOV = Drawing.Color.FromArgb(80, 80, 84)

FONT_TITLE = Drawing.Font("Segoe UI", 12, Drawing.FontStyle.Bold,    Drawing.GraphicsUnit.Point)
FONT_BODY  = Drawing.Font("Segoe UI",  9, Drawing.FontStyle.Regular, Drawing.GraphicsUnit.Point)
FONT_SMALL = Drawing.Font("Segoe UI",  8, Drawing.FontStyle.Regular, Drawing.GraphicsUnit.Point)
FONT_LABEL = Drawing.Font("Segoe UI",  8, Drawing.FontStyle.Bold,    Drawing.GraphicsUnit.Point)
FONT_BTN   = Drawing.Font("Segoe UI",  9, Drawing.FontStyle.Bold,    Drawing.GraphicsUnit.Point)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 2 – UI FACTORY HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _make_label(text, font, fore, back, x, y, w, h,
                align=Drawing.ContentAlignment.MiddleLeft):
    lbl           = WinForms.Label()
    lbl.Text      = text
    lbl.Font      = font
    lbl.ForeColor = fore
    lbl.BackColor = back
    lbl.Location  = Drawing.Point(x, y)
    lbl.Size      = Drawing.Size(w, h)
    lbl.TextAlign = align
    lbl.AutoSize  = False
    return lbl


def _make_button(text, x, y, w, h, bg, fg, on_click):
    btn                                   = WinForms.Button()
    btn.Text                              = text
    btn.Font                              = FONT_BTN
    btn.ForeColor                         = fg
    btn.BackColor                         = bg
    btn.FlatStyle                         = WinForms.FlatStyle.Flat
    btn.FlatAppearance.BorderSize         = 0
    btn.FlatAppearance.MouseOverBackColor = (
        CLR_OK_HOVER if bg == CLR_OK_BG else CLR_CANCEL_HOV
    )
    btn.Location  = Drawing.Point(x, y)
    btn.Size      = Drawing.Size(w, h)
    btn.Click    += on_click
    return btn


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 3 – CONFIRMATION DIALOG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ConfirmDialog(WinForms.Form):
    """
    Dark-themed WinForms dialog summarising what will be created.
    User clicks "Create Parameters" to proceed, or Cancel to exit.
    """

    FORM_W    = 520
    COL_LABEL = 150
    COL_VALUE = 318
    ROW_H     = 28

    ROWS_TEMPLATE = [
        ("Parameter Name",  None),          # filled per-parameter
        ("Category",        "Rooms"),
        ("Parameter Type",  "Instance"),
        ("Data Type",       None),          # filled per-parameter (Text / Number)
        ("Group Under",     "Identity Data"),
        ("Varies by Group", "Yes"),
    ]

    def __init__(self):
        WinForms.Form.__init__(self)

        self.Text            = "FLS Parameter Creator"
        self.Size            = Drawing.Size(self.FORM_W, 480)
        self.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
        # Correct enum name is FormStartPosition, NOT StartPosition
        self.StartPosition   = WinForms.FormStartPosition.CenterScreen
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.BackColor       = CLR_BG
        self._accepted       = [False]

        self._build_ui()

    # ──────────────────────────────────────────────────────────
    def _build_ui(self):
        y = 0

        # ── Blue header bar ───────────────────────────────────
        header           = WinForms.Panel()
        header.BackColor = CLR_HEADER
        header.Location  = Drawing.Point(0, y)
        header.Size      = Drawing.Size(self.FORM_W, 56)
        self.Controls.Add(header)

        header.Controls.Add(_make_label(
            "FLS Parameter Creator", FONT_TITLE,
            Drawing.Color.White, CLR_HEADER,
            16, 8, 400, 26
        ))
        header.Controls.Add(_make_label(
            "The following Project Parameters will be added to your document.",
            FONT_BODY, Drawing.Color.FromArgb(210, 230, 255), CLR_HEADER,
            16, 32, 460, 18
        ))
        y += 56

        # ── Section label ─────────────────────────────────────
        self.Controls.Add(_make_label(
            "Parameters to be created:", FONT_LABEL,
            CLR_MUTED, CLR_BG,
            20, y + 14, 300, 18
        ))
        y += 40

        # ── One info-card per parameter ───────────────────────
        for pname, dtype_label, _is_num in PARAM_DEFS:

            table_h = len(self.ROWS_TEMPLATE) * self.ROW_H + 26

            # 1-px border shell
            border           = WinForms.Panel()
            border.BackColor = CLR_BORDER
            border.Location  = Drawing.Point(20, y)
            border.Size      = Drawing.Size(self.FORM_W - 40, table_h + 2)
            self.Controls.Add(border)

            # Inner content panel
            inner           = WinForms.Panel()
            inner.BackColor = CLR_PANEL
            inner.Location  = Drawing.Point(1, 1)
            inner.Size      = Drawing.Size(border.Width - 2, table_h)
            border.Controls.Add(inner)

            # Accent header row
            name_row           = WinForms.Panel()
            name_row.BackColor = CLR_HEADER
            name_row.Location  = Drawing.Point(0, 0)
            name_row.Size      = Drawing.Size(inner.Width, 26)
            inner.Controls.Add(name_row)

            name_row.Controls.Add(_make_label(
                u"\u2713  {}".format(pname),
                FONT_LABEL, Drawing.Color.White, CLR_HEADER,
                10, 0, inner.Width - 20, 26
            ))

            # Data rows
            for ri, (field, value) in enumerate(self.ROWS_TEMPLATE):
                if field == "Parameter Name":
                    value = pname
                elif field == "Data Type":
                    value = dtype_label   # "Text" or "Number" per param

                row_y  = 26 + ri * self.ROW_H
                row_bg = CLR_ROW_A if ri % 2 == 0 else CLR_ROW_B

                row_pnl           = WinForms.Panel()
                row_pnl.BackColor = row_bg
                row_pnl.Location  = Drawing.Point(0, row_y)
                row_pnl.Size      = Drawing.Size(inner.Width, self.ROW_H)
                inner.Controls.Add(row_pnl)

                row_pnl.Controls.Add(_make_label(
                    field, FONT_LABEL, CLR_MUTED, row_bg,
                    10, 0, self.COL_LABEL, self.ROW_H
                ))

                sep           = WinForms.Panel()
                sep.BackColor = CLR_BORDER
                sep.Location  = Drawing.Point(self.COL_LABEL, 6)
                sep.Size      = Drawing.Size(1, self.ROW_H - 12)
                row_pnl.Controls.Add(sep)

                row_pnl.Controls.Add(_make_label(
                    value, FONT_BODY, CLR_TEXT, row_bg,
                    self.COL_LABEL + 12, 0, self.COL_VALUE, self.ROW_H
                ))

            y += table_h + 2 + 12

        y += 6

        # ── Divider ───────────────────────────────────────────
        div           = WinForms.Panel()
        div.BackColor = CLR_BORDER
        div.Location  = Drawing.Point(0, y)
        div.Size      = Drawing.Size(self.FORM_W, 1)
        self.Controls.Add(div)
        y += 12

        # ── Footer note ───────────────────────────────────────
        self.Controls.Add(_make_label(
            u"\u26a0  Already-existing parameters will be skipped automatically.",
            FONT_SMALL, CLR_MUTED, CLR_BG,
            20, y, self.FORM_W - 40, 18
        ))
        y += 26

        # ── Buttons ───────────────────────────────────────────
        self.Controls.Add(_make_button(
            "Cancel",
            self.FORM_W - 222, y, 94, 30,
            CLR_CANCEL_BG, CLR_TEXT, self._on_cancel
        ))
        self.Controls.Add(_make_button(
            "Create Parameters",
            self.FORM_W - 120, y, 104, 30,
            CLR_OK_BG, Drawing.Color.White, self._on_ok
        ))

        self.ClientSize = Drawing.Size(self.FORM_W, y + 46)

    # ──────────────────────────────────────────────────────────
    def _on_ok(self, sender, e):
        self._accepted[0] = True
        self.Close()

    def _on_cancel(self, sender, e):
        self._accepted[0] = False
        self.Close()

    @property
    def accepted(self):
        return self._accepted[0]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 4 – PARAMETER CREATION HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _existing_param_names(doc):
    """Return a set of all parameter names already bound in this document."""
    names = set()
    it = doc.ParameterBindings.ForwardIterator()
    while it.MoveNext():
        try:
            names.add(it.Key.Name)
        except Exception:
            pass
    return names


def _make_ext_def_options(name, is_number=False):
    """
    ExternalDefinitionCreationOptions for a Text or Number parameter.
    Tries SpecTypeId (Revit 2022+) first then falls back to ParameterType (older).
    """
    try:
        from Autodesk.Revit.DB import SpecTypeId
        spec = SpecTypeId.Number if is_number else SpecTypeId.String.Text
        opts = ExternalDefinitionCreationOptions(name, spec)
    except Exception:
        from Autodesk.Revit.DB import ParameterType
        ptype = ParameterType.Number if is_number else ParameterType.Text
        opts = ExternalDefinitionCreationOptions(name, ptype)
    opts.UserModifiable = True
    opts.Visible        = True
    return opts


def _find_shared_param_element(doc, guid):
    """Return the SharedParameterElement matching the given GUID, or None."""
    for spe in (FilteredElementCollector(doc)
                .OfClass(SharedParameterElement)
                .ToElements()):
        try:
            if spe.GuidValue == guid:
                return spe
        except Exception:
            pass
    return None


def create_fls_parameters(doc, app):
    """
    Create FLS parameters via a temporary shared-parameter file.
    Returns (created_names, skipped_names).
    """
    existing  = _existing_param_names(doc)
    to_create = [(n, is_num) for n, _lbl, is_num in PARAM_DEFS if n not in existing]
    skipped   = [n          for n, _lbl, _num    in PARAM_DEFS if n in existing]

    if not to_create:
        return [], skipped

    # ── Swap in a temp shared-parameter file ──────────────────
    original_spf     = app.SharedParametersFilename
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="fls_params_")
    os.close(tmp_fd)

    try:
        app.SharedParametersFilename = tmp_path
        def_file = app.OpenSharedParameterFile()

        grp = def_file.Groups.get_Item("FLS Parameters")
        if grp is None:
            grp = def_file.Groups.Create("FLS Parameters")

        cat_set   = app.Create.NewCategorySet()
        rooms_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Rooms)
        cat_set.Insert(rooms_cat)

        # ── Transaction 1: bind parameters ────────────────────
        t = Transaction(doc, "FLS: Create Project Parameters")
        t.Start()

        created       = []
        created_guids = []

        for name, is_num in to_create:
            ext_def = grp.Definitions.Create(_make_ext_def_options(name, is_num))
            binding = app.Create.NewInstanceBinding(cat_set)
            doc.ParameterBindings.Insert(ext_def, binding, IDENTITY_DATA_GROUP)
            created.append(name)
            created_guids.append(ext_def.GUID)

        t.Commit()

        # ── Transaction 2: allow varying across groups ─────────
        # Must be a separate transaction – cannot run in the same one as Insert.
        t2 = Transaction(doc, "FLS: Allow Varying Across Groups")
        t2.Start()
        for guid in created_guids:
            spe = _find_shared_param_element(doc, guid)
            if spe is not None:
                try:
                    spe.SetAllowsVaryingAcrossGroups(doc, True)
                except Exception:
                    pass    # API not present in all Revit versions
        t2.Commit()

    finally:
        # Restore original shared-parameter file no matter what
        app.SharedParametersFilename = original_spf if original_spf else ""
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    return created, skipped


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 5 – MAIN ENTRY POINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

dlg = ConfirmDialog()
dlg.ShowDialog()

if not dlg.accepted:
    script.exit()

from pyrevit import forms as _forms

try:
    created, skipped = create_fls_parameters(doc, app)
except Exception as ex:
    _forms.alert(
        "Parameter creation failed.\n\nDetails:\n{}".format(str(ex)),
        title=u"FLS Parameter Creator \u2013 Error"
    )
    script.exit()

if created:
    msg = u"Successfully created {} parameter(s):\n".format(len(created))
    msg += u"\n".join(u"  \u2713  {}".format(n) for n in created)
else:
    msg = u"No new parameters were created."

if skipped:
    msg += u"\n\nAlready present (skipped):\n"
    msg += u"\n".join(u"  \u2014  {}".format(n) for n in skipped)

_forms.alert(msg, title=u"FLS Parameter Creator \u2013 Done")