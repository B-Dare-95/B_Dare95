# -*- coding: utf-8 -*-
"""
Create Shaft Function Parameter
--------------------------------
Creates a Project Parameter named "Shaft Function" bound to
Shaft Opening category as an Instance / Text / Identity Data parameter
with "values can vary by group instances" enabled.

Uses a temporary shared-parameter file under the hood (required by
the Revit API to create project parameters programmatically).
"""
__title__   = "Create\nShaft Param"
__author__  = "B_Dare95"
__version__ = "1.0.0"

# ── stdlib / CLR ────────────────────────────────────────────────────────────
import os
import clr

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System
from System.Windows.Forms import (
    Form, Label, Button, PictureBox, PictureBoxSizeMode,
    DialogResult, MessageBox, MessageBoxButtons, MessageBoxIcon,
    FormStartPosition, FormBorderStyle, FlatStyle,
    Application
)
from System.Drawing import (
    Size, Point, Color, Font, FontStyle, SolidBrush,
    Rectangle, Bitmap, Graphics
)

# ── pyRevit / Revit API ──────────────────────────────────────────────────────
from pyrevit import revit, script
from Autodesk.Revit.DB import (
    Transaction, BuiltInCategory, ForgeTypeId
)

# Identity Data parameter group  (replaces the deprecated BuiltInParameterGroup enum)
IDENTITY_DATA_GROUP = ForgeTypeId("autodesk.parameter.group:identityData-1.0.0")

doc = revit.doc
app = doc.Application

# ════════════════════════════════════════════════════════════════════════════
#  CONFIRMATION DIALOG
# ════════════════════════════════════════════════════════════════════════════

# Colour palette (matches the dark-themed pyRevit WinForms style)
CLR_BG          = Color.FromArgb(30,  30,  30)
CLR_PANEL       = Color.FromArgb(45,  45,  48)
CLR_BORDER      = Color.FromArgb(63,  63,  70)
CLR_ACCENT      = Color.FromArgb(0,   122, 204)
CLR_ACCENT_HOV  = Color.FromArgb(28,  151, 234)
CLR_WHITE       = Color.White
CLR_MUTED       = Color.FromArgb(160, 160, 160)
CLR_WARN_BG     = Color.FromArgb(50,  40,  10)
CLR_WARN_BORDER = Color.FromArgb(200, 160, 0)
CLR_WARN_TXT    = Color.FromArgb(240, 200, 60)

PARAM_ROWS = [
    ("Parameter Name",        "Shaft Function"),
    ("Category",              "Shaft Openings"),
    ("Parameter Type",        "Instance"),
    ("Data Type",             "Text"),
    ("Group Under",           "Identity Data"),
    ("Values Vary by Group",  "Yes"),
]

DIALOG_W = 480
DIALOG_H = 390


def _make_label(text, font, color, loc, size):
    lbl = Label()
    lbl.Text      = text
    lbl.Font      = font
    lbl.ForeColor = color
    lbl.Location  = Point(*loc)
    lbl.Size      = Size(*size)
    lbl.BackColor = Color.Transparent
    return lbl


class ConfirmDialog(Form):
    def __init__(self):
        # ── window chrome ────────────────────────────────────────────────
        self.Text            = "Create Project Parameter"
        self.ClientSize      = Size(DIALOG_W, DIALOG_H)
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.BackColor       = CLR_BG

        fnt_title   = Font("Segoe UI", 13, FontStyle.Bold)
        fnt_sub     = Font("Segoe UI",  9, FontStyle.Regular)
        fnt_key     = Font("Segoe UI",  9, FontStyle.Regular)
        fnt_val     = Font("Segoe UI",  9, FontStyle.Bold)
        fnt_warn    = Font("Segoe UI",  8, FontStyle.Italic)
        fnt_btn     = Font("Segoe UI", 10, FontStyle.Regular)

        # ── header ───────────────────────────────────────────────────────
        self.Controls.Add(_make_label(
            "Create Project Parameter",
            fnt_title, CLR_WHITE, (24, 20), (380, 30)
        ))
        self.Controls.Add(_make_label(
            "The following parameter will be added to this project:",
            fnt_sub, CLR_MUTED, (24, 52), (420, 20)
        ))

        # ── info card ────────────────────────────────────────────────────
        card_top = 82
        card_h   = len(PARAM_ROWS) * 30 + 16
        card     = _make_panel(24, card_top, DIALOG_W - 48, card_h,
                               CLR_PANEL, CLR_BORDER)
        self.Controls.Add(card)

        for i, (key, val) in enumerate(PARAM_ROWS):
            y = 8 + i * 30
            card.Controls.Add(_make_label(
                key + ":", fnt_key, CLR_MUTED, (14, y), (180, 22)
            ))
            card.Controls.Add(_make_label(
                val, fnt_val, CLR_WHITE, (200, y), (card.Width - 215, 22)
            ))

        # ── warning note ─────────────────────────────────────────────────
        note_top = card_top + card_h + 14
        note     = _make_panel(24, note_top, DIALOG_W - 48, 46,
                               CLR_WARN_BG, CLR_WARN_BORDER)
        self.Controls.Add(note)
        note.Controls.Add(_make_label(
            u"\u26a0  A temporary shared-parameter file will be used internally "
            u"by the Revit API. It will be deleted automatically after the "
            u"parameter is created.",
            fnt_warn, CLR_WARN_TXT, (10, 6), (note.Width - 20, 36)
        ))

        # ── buttons ──────────────────────────────────────────────────────
        btn_top = note_top + 58

        ok_btn = _make_button(
            "OK  –  Create Parameter", fnt_btn,
            CLR_WHITE, CLR_ACCENT, CLR_ACCENT_HOV,
            DIALOG_W - 24 - 220, btn_top, 220, 36
        )
        ok_btn.DialogResult = DialogResult.OK
        self.Controls.Add(ok_btn)

        cancel_btn = _make_button(
            "Cancel", fnt_btn,
            CLR_MUTED, CLR_BORDER, CLR_PANEL,
            DIALOG_W - 24 - 220 - 90 - 8, btn_top, 90, 36
        )
        cancel_btn.DialogResult = DialogResult.Cancel
        self.Controls.Add(cancel_btn)

        self.AcceptButton = ok_btn
        self.CancelButton = cancel_btn


# ── helper UI factories ──────────────────────────────────────────────────────

def _make_panel(x, y, w, h, bg, border_color):
    from System.Windows.Forms import Panel
    p = Panel()
    p.Location  = Point(x, y)
    p.Size      = Size(w, h)
    p.BackColor = bg

    # Draw border via Paint event
    _border_color = border_color   # capture for closure
    def on_paint(sender, e):
        pen = System.Drawing.Pen(_border_color, 1)
        e.Graphics.DrawRectangle(pen, 0, 0, sender.Width - 1, sender.Height - 1)
    p.Paint += on_paint
    return p


def _make_button(text, font, fg, bg, hover_bg, x, y, w, h):
    btn = Button()
    btn.Text      = text
    btn.Font      = font
    btn.ForeColor = fg
    btn.BackColor = bg
    btn.FlatStyle = FlatStyle.Flat
    btn.FlatAppearance.BorderSize  = 0
    btn.FlatAppearance.MouseOverBackColor = hover_bg
    btn.Location  = Point(x, y)
    btn.Size      = Size(w, h)
    btn.Cursor    = System.Windows.Forms.Cursors.Hand
    return btn


# ════════════════════════════════════════════════════════════════════════════
#  PARAMETER CREATION LOGIC
# ════════════════════════════════════════════════════════════════════════════

PARAM_NAME      = "Shaft Function"
PARAM_GROUP_HDR = "ShaftFunctionParams"        # group name inside the temp SPF
TEMP_SPF_NAME   = "_temp_shaft_function_spf.txt"


def _parameter_already_exists():
    """Return True if a parameter named 'Shaft Function' is already bound."""
    it = doc.ParameterBindings.ForwardIterator()
    while it.MoveNext():
        if it.Key.Name == PARAM_NAME:
            return True
    return False


def _build_temp_spf(path):
    """Write a minimal valid Revit Shared Parameter File to *path*."""
    guid = str(System.Guid.NewGuid())
    lines = [
        "# This is a Revit shared parameter file.",
        "# Do not edit manually.",
        "*META\tVERSION\tMINVERSION",
        "META\t2\t1",
        "*GROUP\tID\tNAME",
        "GROUP\t1\t" + PARAM_GROUP_HDR,
        "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE"
            "\tDESCRIPTION\tUSERMODIFIABLE\tHIDEWHENNOVALUE",
        "PARAM\t{0}\t{1}\tTEXT\t\t1\t1\t\t1\t0".format(guid, PARAM_NAME),
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(lines))


def create_shaft_function_parameter():
    """
    Creates the 'Shaft Function' project parameter.
    Returns True on success, False if it already existed.
    Raises Exception on any error.
    """
    if _parameter_already_exists():
        return False    # caller will notify the user

    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or "C:\\Temp"
    temp_spf  = os.path.join(temp_dir, TEMP_SPF_NAME)
    original_spf = app.SharedParametersFilename   # may be "" if none set

    try:
        # 1 ─ Build temp shared-parameter file
        _build_temp_spf(temp_spf)

        # 2 ─ Point Revit at the temp file
        app.SharedParametersFilename = temp_spf
        sp_file = app.OpenSharedParameterFile()
        if sp_file is None:
            raise Exception(
                "Revit could not open the temporary shared-parameter file:\n"
                + temp_spf
            )

        # 3 ─ Retrieve the ExternalDefinition
        grp = sp_file.Groups.get_Item(PARAM_GROUP_HDR)
        if grp is None:
            raise Exception("Parameter group '{0}' not found in temp SPF."
                            .format(PARAM_GROUP_HDR))

        ext_def = grp.Definitions.get_Item(PARAM_NAME)
        if ext_def is None:
            raise Exception("Definition '{0}' not found in temp SPF."
                            .format(PARAM_NAME))

        # 4 ─ Build category set  (Shaft Openings only)
        cat_set      = app.Create.NewCategorySet()
        shaft_cat    = doc.Settings.Categories.get_Item(
                            BuiltInCategory.OST_ShaftOpening)
        if shaft_cat is None:
            raise Exception(
                "The 'Shaft Opening' category could not be found in "
                "this Revit project. Make sure you are running the script "
                "in an Architectural or MEP model."
            )
        cat_set.Insert(shaft_cat)

        # 5 ─ Instance binding
        instance_binding = app.Create.NewInstanceBinding(cat_set)

        # 6 ─ Insert inside a transaction
        with Transaction(doc, "Create Shaft Function Parameter") as t:
            t.Start()

            success = doc.ParameterBindings.Insert(
                ext_def,
                instance_binding,
                IDENTITY_DATA_GROUP
            )

            if not success:
                t.RollBack()
                raise Exception(
                    "ParameterBindings.Insert() returned False.\n"
                    "The parameter may already exist under a different binding."
                )

            # 7 ─ Enable "Values can vary by group instances"
            it = doc.ParameterBindings.ForwardIterator()
            while it.MoveNext():
                internal_def = it.Key
                if internal_def.Name == PARAM_NAME:
                    try:
                        internal_def.SetAllowVaryBetweenGroups(doc, True)
                    except Exception:
                        pass    # non-fatal – available in Revit 2019+
                    break

            t.Commit()

        return True

    finally:
        # ── always restore the original SPF and clean up ─────────────────
        try:
            app.SharedParametersFilename = original_spf
        except Exception:
            pass
        try:
            if os.path.exists(temp_spf):
                os.remove(temp_spf)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

# ── Show confirmation dialog ─────────────────────────────────────────────────
dlg = ConfirmDialog()
if dlg.ShowDialog() != DialogResult.OK:
    script.exit()

# ── Execute ──────────────────────────────────────────────────────────────────
try:
    created = create_shaft_function_parameter()

    if created:
        MessageBox.Show(
            u"Parameter \u2018Shaft Function\u2019 was created successfully!\n\n"
            u"  \u2022 Category   : Shaft Openings\n"
            u"  \u2022 Type       : Instance / Text\n"
            u"  \u2022 Group      : Identity Data\n"
            u"  \u2022 Vary by Group : Yes",
            "Parameter Created",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information
        )
    else:
        MessageBox.Show(
            u"The parameter \u2018Shaft Function\u2019 already exists in "
            u"this project.\n\nNo changes were made.",
            "Already Exists",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information
        )

except Exception as ex:
    MessageBox.Show(
        u"An error occurred while creating the parameter:\n\n" + str(ex),
        "Error",
        MessageBoxButtons.OK,
        MessageBoxIcon.Error
    )