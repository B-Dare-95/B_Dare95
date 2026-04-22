# -*- coding: utf-8 -*-
"""
FLS Occupancy Calculator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generates an Excel workbook with three sheets:

  Sheet 1 – NET Rooms
      Rooms where FLS Area Measurement = "NET"
      Occupant count = Room Area (m²) ÷ FLS Occupancy Factor

  Sheet 2 – GROSS Rooms
      Rooms where FLS Area Measurement = "GROSS"
      Occupant count = Gross Area from FLS Area Plans ÷ FLS Occupancy Factor

  Sheet 3 – By Fixed Seat
      Rooms where FLS Area Measurement = "N.O.SEATS"
      Occupant count = number of fixed-seat furniture items
      (furniture families whose name contains "FIX_CHR")

The user is prompted to choose the save location before the
workbook is created. The file is opened automatically on completion.

Prerequisites:
  Run FLS Parameter Creator     → creates FLS parameters on Rooms
  Run FLS Area Scheme Creator   → creates "FLS" area scheme
  Run FLS Area Plan Creator     → populates FLS area plan boundaries
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Author  : B_Dare95
Version : 2.0.0
"""

# ──────────────────────────────────────────────────────────────
# IMPORTS
# ──────────────────────────────────────────────────────────────
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System.Windows.Forms')

import System.Windows.Forms as WinForms
import System.Diagnostics   as Diagnostics

from collections import defaultdict
import xlsxwriter

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    UnitUtils,
    UnitTypeId,
)
from pyrevit import forms, script

# ──────────────────────────────────────────────────────────────
# REVIT HANDLES
# ──────────────────────────────────────────────────────────────
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ──────────────────────────────────────────────────────────────
# FLS CONSTANTS
# ──────────────────────────────────────────────────────────────
FLS_AREA_MEAS_PARAM  = "FLS Area Measurement"   # "NET" / "GROSS" / "N.O.SEATS"
FLS_FACTOR_PARAM     = "FLS Occupancy Factor"   # numeric string e.g. "14"
FLS_OCCUPANCY_PARAM  = "FLS Occupancy"          # descriptive text
FLS_SCHEME_NAME      = "FLS"                    # area scheme name

FIXED_SEAT_TAG       = "FIX_CHR"               # furniture name substring


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 1 – CHOOSE SAVE LOCATION  (before any data work)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

dlg                 = WinForms.SaveFileDialog()
dlg.Title           = u"Save FLS Occupancy Calculator"
dlg.Filter          = u"Excel Workbook (*.xlsx)|*.xlsx"
dlg.FileName        = u"FLS_Occupancy_Calculator.xlsx"
dlg.OverwritePrompt = True   # WinForms handles the "file exists" prompt natively

dialog_result = dlg.ShowDialog()

if dialog_result != WinForms.DialogResult.OK:
    script.exit()

save_path = dlg.FileName


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 2 – COLLECT ROOM DATA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _fls_param(element, pname):
    """Return element parameter value as string, or '' if absent."""
    p = element.LookupParameter(pname)
    if p is None:
        return ""
    return (p.AsString() or "").strip()


def _fls_param_double(element, pname):
    """Return element Number parameter value as float, or 0.0 if absent/invalid."""
    p = element.LookupParameter(pname)
    if p is None:
        return 0.0
    try:
        return p.AsDouble()
    except Exception:
        return 0.0


def _to_float(text):
    """Parse a string to float; return 0.0 on failure (e.g. 'See Sec. 1004.6')."""
    try:
        return float(text)
    except (ValueError, TypeError, AttributeError):
        return 0.0


def _m2(internal_value):
    """Convert Revit internal area (sq ft) to square metres."""
    return UnitUtils.ConvertFromInternalUnits(internal_value, UnitTypeId.SquareMeters)


# ── Collect all placed rooms (area > 0) ───────────────────────
all_rooms = [
    r for r in FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Rooms)
                 .WhereElementIsNotElementType()
                 .ToElements()
    if r.Area > 0
]

net_rooms    = [r for r in all_rooms if _fls_param(r, FLS_AREA_MEAS_PARAM) == "NET"]
gross_rooms  = [r for r in all_rooms if _fls_param(r, FLS_AREA_MEAS_PARAM) == "GROSS"]
seat_rooms   = [r for r in all_rooms if _fls_param(r, FLS_AREA_MEAS_PARAM) == "N.O.SEATS"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 3 – BUILD DATA TABLES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── NET rooms ─────────────────────────────────────────────────
net_data = []
for room in net_rooms:
    name       = _fls_param(room, "Name") or room.Name
    number     = _fls_param(room, "Number") or ""
    area_m2    = _m2(room.LookupParameter("Area").AsDouble())
    occupancy  = _fls_param(room, FLS_OCCUPANCY_PARAM)
    factor     = _fls_param_double(room, FLS_FACTOR_PARAM)   # Number param → AsDouble
    factor_str = "{:.2f}".format(factor) if factor > 0 else ""
    occupants  = round(area_m2 / factor, 2) if factor > 0 else 0

    net_data.append((name, number, round(area_m2, 3),
                     occupancy, factor_str, occupants))

# ── GROSS rooms – area from FLS Area Plans ────────────────────
# Build a lookup: (room_name, room_number) → gross area (m²) from FLS area plans
fls_area_lookup = {}

all_areas = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_Areas)
             .WhereElementIsNotElementType()
             .ToElements())

for area in all_areas:
    try:
        # Filter to FLS area scheme only
        if area.AreaScheme.Name != FLS_SCHEME_NAME:
            continue
        a_name   = (area.LookupParameter("Name").AsString()   or "").strip()
        a_number = (area.LookupParameter("Number").AsString() or "").strip()
        a_m2     = _m2(area.LookupParameter("Area").AsDouble())
        if a_m2 > 0:
            fls_area_lookup[(a_name, a_number)] = a_m2
    except Exception:
        pass

gross_data = []
for room in gross_rooms:
    name       = _fls_param(room, "Name") or room.Name
    number     = _fls_param(room, "Number") or ""
    occupancy  = _fls_param(room, FLS_OCCUPANCY_PARAM)
    factor     = _fls_param_double(room, FLS_FACTOR_PARAM)   # Number param → AsDouble
    factor_str = "{:.2f}".format(factor) if factor > 0 else ""

    # Prefer exact (name, number) match; fall back to name-only match
    area_m2 = fls_area_lookup.get(
        (name.strip(), number.strip()),
        fls_area_lookup.get((name.strip(), ""), 0.0)
    )
    occupants = round(area_m2 / factor, 2) if factor > 0 else 0

    gross_data.append((name, number, round(area_m2, 3),
                       occupancy, factor_str, occupants))

# ── By-seat rooms – count fixed furniture in room ────────────
all_furniture = (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Furniture)
                 .WhereElementIsNotElementType()
                 .ToElements())

fixed_seats = [s for s in all_furniture if FIXED_SEAT_TAG in s.Name]

seat_data = []
for room in seat_rooms:
    name      = _fls_param(room, "Name") or room.Name
    number    = _fls_param(room, "Number") or ""
    occupancy = _fls_param(room, FLS_OCCUPANCY_PARAM)

    count = 0
    for seat in fixed_seats:
        try:
            if room.IsPointInRoom(seat.Location.Point):
                count += 1
        except Exception:
            pass

    seat_data.append((name, number, occupancy, count))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 4 – CREATE WORKBOOK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

try:
    workbook = xlsxwriter.Workbook(save_path)

    # ── Shared formats ─────────────────────────────────────────
    hdr_fmt = workbook.add_format({
        'bold'        : True,
        'bg_color'    : '#1F4E79',
        'font_color'  : 'white',
        'font_size'   : 11,
        'border'      : 2,
        'border_color': '#000000',
        'align'       : 'center',
        'valign'      : 'vcenter',
    })
    data_fmt = workbook.add_format({
        'border'      : 1,
        'border_color': '#BFBFBF',
        'align'       : 'left',
        'valign'      : 'vcenter',
    })
    num_fmt = workbook.add_format({
        'border'      : 1,
        'border_color': '#BFBFBF',
        'align'       : 'right',
        'valign'      : 'vcenter',
        'num_format'  : '#,##0.00',
    })
    int_fmt = workbook.add_format({
        'border'      : 1,
        'border_color': '#BFBFBF',
        'align'       : 'right',
        'valign'      : 'vcenter',
        'num_format'  : '#,##0',
    })
    subtotal_fmt = workbook.add_format({
        'bold'        : True,
        'bg_color'    : '#D6E4F0',
        'border'      : 1,
        'border_color': '#2E75B6',
        'align'       : 'right',
        'valign'      : 'vcenter',
        'num_format'  : '#,##0',
    })

    # ──────────────────────────────────────────────────────────
    def _write_sheet(ws, headers, col_widths, rows, numeric_cols,
                     total_col=None, total_label_col=0):
        """
        Write headers + data rows to a worksheet.

        headers      : list of column header strings
        col_widths   : list of column widths
        rows         : list of tuples, one per data row
        numeric_cols : set of 0-based col indices to use num_fmt / int_fmt
        total_col    : column index to sum for a TOTAL row (None = no total)
        """
        # Set column widths
        for ci, w in enumerate(col_widths):
            ws.set_column(ci, ci, w)
        ws.set_row(0, 22)

        # Headers
        for ci, h in enumerate(headers):
            ws.write(0, ci, h, hdr_fmt)

        # Data
        for ri, row in enumerate(rows, start=1):
            ws.set_row(ri, 18)
            for ci, val in enumerate(row):
                if ci in numeric_cols:
                    ws.write(ri, ci, val, num_fmt)
                else:
                    ws.write(ri, ci, val, data_fmt)

        # Optional total row
        if total_col is not None and rows:
            total_row = len(rows) + 1
            ws.set_row(total_row, 20)
            for ci in range(len(headers)):
                if ci == total_label_col:
                    ws.write(total_row, ci, "TOTAL", subtotal_fmt)
                elif ci == total_col:
                    ws.write(total_row, ci,
                             sum(r[ci] for r in rows),
                             subtotal_fmt)
                else:
                    ws.write(total_row, ci, "", subtotal_fmt)

    # ── Sheet 1: NET Rooms ─────────────────────────────────────
    ws1 = workbook.add_worksheet("NET Rooms")
    _write_sheet(
        ws1,
        headers     = ["Room Name", "Room Number", u"Area (m\u00b2)",
                       "FLS Occupancy", "Load Factor (m\u00b2/person)",
                       "No. of Occupants"],
        col_widths  = [35, 16, 14, 28, 26, 20],
        rows        = net_data,
        numeric_cols= {2, 5},
        total_col   = 5,
        total_label_col = 0,
    )

    # ── Sheet 2: GROSS Rooms ───────────────────────────────────
    ws2 = workbook.add_worksheet("GROSS Rooms")
    _write_sheet(
        ws2,
        headers     = ["Room Name", "Room Number", u"Gross Area (m\u00b2)",
                       "FLS Occupancy", "Load Factor (m\u00b2/person)",
                       "No. of Occupants"],
        col_widths  = [35, 16, 16, 28, 26, 20],
        rows        = gross_data,
        numeric_cols= {2, 5},
        total_col   = 5,
        total_label_col = 0,
    )

    # ── Sheet 3: By Fixed Seat ────────────────────────────────
    ws3 = workbook.add_worksheet("By Fixed Seat")
    _write_sheet(
        ws3,
        headers     = ["Room Name", "Room Number",
                       "FLS Occupancy", "No. of Fixed Seats"],
        col_widths  = [35, 16, 28, 20],
        rows        = seat_data,
        numeric_cols= {3},
        total_col   = 3,
        total_label_col = 0,
    )

    workbook.close()

except Exception as ex:
    forms.alert(
        u"Failed to create the Excel file.\n\nDetails:\n{}".format(str(ex)),
        title=u"FLS Occupancy Calculator \u2013 Error"
    )
    script.exit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 5 – OPEN FILE & SUMMARISE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

try:
    Diagnostics.Process.Start(save_path)
except Exception:
    pass   # Opening silently fails on some machines; file was still saved

total_net   = sum(r[5] for r in net_data)
total_gross = sum(r[5] for r in gross_data)
total_seat  = sum(r[3] for r in seat_data)

forms.alert(
    u"FLS Occupancy Calculator exported successfully!\n\n"
    u"  NET rooms processed       :  {} rooms  ({} occupants)\n"
    u"  GROSS rooms processed     :  {} rooms  ({} occupants)\n"
    u"  By-seat rooms processed   :  {} rooms  ({} seats)\n\n"
    u"  Saved to:\n  {}".format(
        len(net_data),   int(total_net),
        len(gross_data), int(total_gross),
        len(seat_data),  int(total_seat),
        save_path
    ),
    title=u"FLS Occupancy Calculator \u2013 Done"
)