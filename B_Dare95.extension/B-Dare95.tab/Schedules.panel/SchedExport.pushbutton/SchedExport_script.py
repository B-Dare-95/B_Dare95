# -*- coding: utf-8 -*-
__title__     = "SchedExport"
__author__    = "Oscar Mendoza"
__doc__ = """Version = 1.1
Date    = 06.04.2026
_____________________________________________________________________
Description:
Export data to schedules
_____________________________________________________________________
How-to:
-> Run the script
-> Select Schedules to export
-> Choose where to save the new Excel file
_____________________________________________________________________
Last update:
- [06.04.26] - 1.1 Changed to create new Excel file via SaveFileDialog
- [20.06.25] - 1.0 RELEASE
________________________________________________________________________
Author: Oscar Mendoza (Reworked by Mohamed Bedair using Claude AI)"""

__helpurl__ = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
__min_revit_ver__ = 2021
__max_revit_ver__ = 2025

# ⬇️ IMPORTS
#--------------------------------------------------------------------------
from Autodesk.Revit.DB import *
from pyrevit import forms
from rpw.ui.forms import Alert
import xlsxwriter

# IronPython-compatible Save dialog
import clr
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import SaveFileDialog, DialogResult

# 📦 VARIABLES
#--------------------------------------------------------------------------
uidoc = __revit__.ActiveUIDocument
doc   = __revit__.ActiveUIDocument.Document

# 💻 MAIN
#--------------------------------------------------------------------------

## 1. Collect schedules
selected_schedules = forms.select_schedules(title="OMBIM_AUTOMATION - Export Schedules")

if not selected_schedules:
    forms.alert(
        "No schedule selected. Please try again.",
        title="OMBIM_AUTOMATION - Export Schedules",
        exitscript=True
    )

## 2. Validate schedule name length (Excel sheet name limit: 31 chars)
schedules_exceed = [
    x for x in selected_schedules
    if len(Element.Name.GetValue(x)) > 31
]

if schedules_exceed:
    msg  = "\n⚠ Schedules exceeding the 31-character sheet name limit:\n"
    msg += "\n".join("  - {}".format(Element.Name.GetValue(x)) for x in schedules_exceed)
    forms.alert(
        msg,
        title="OMBIM_AUTOMATION - Name Error",
        exitscript=True
    )

## 3. Save dialog — create a NEW Excel file
dialog = SaveFileDialog()
dialog.Title       = "OMBIM_AUTOMATION - Save New Excel File"
dialog.Filter      = "Excel File (*.xlsx)|*.xlsx"
dialog.DefaultExt  = "xlsx"
dialog.FileName    = "ScheduleExport"   # default suggested name

result = dialog.ShowDialog()

if result != DialogResult.OK or not dialog.FileName:
    forms.alert(
        "No file path selected. Operation cancelled.",
        title="OMBIM_AUTOMATION - Export Schedules",
        exitscript=True
    )

file_path = dialog.FileName

# #### FUNCTIONS ######

def get_data_schedules(list_schedules):
    """Collect data from schedules.
    :param list_schedules: List of ViewSchedule elements
    :return: dict {schedule_name: [[row data], ...]}
    """
    result = {}
    for schedule in list_schedules:
        table         = schedule.GetTableData().GetSectionData(SectionType.Body)
        schedule_name = Element.Name.GetValue(schedule)
        nRows         = table.NumberOfRows
        nColumns      = table.NumberOfColumns

        dataListRow = []
        for row in range(nRows):
            dataListColum = []
            for column in range(nColumns):
                dataListColum.append(
                    TableView.GetCellText(schedule, SectionType.Body, row, column)
                )
            dataListRow.append(dataListColum)

        result[schedule_name] = dataListRow
    return result


def dump(xlfile, datadict):
    """Write data dict to a new Excel workbook.
    :param xlfile:    Full path of the target Excel file
    :param datadict:  {sheet_name: [[row], [row], ...]}
    """
    xlwb = xlsxwriter.Workbook(xlfile)
    header_fmt = xlwb.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1})
    cell_fmt   = xlwb.add_format({'border': 1})

    for xlsheetname, xlsheetdata in datadict.items():
        xlsheet = xlwb.add_worksheet(xlsheetname)
        for idx, row_data in enumerate(xlsheetdata):
            fmt = header_fmt if idx == 0 else cell_fmt
            xlsheet.write_row(idx, 0, row_data, fmt)

    xlwb.close()


### CODE ###
dictionary_data = get_data_schedules(selected_schedules)
dump(file_path, dictionary_data)

## FINAL REPORT ##
names = list(dictionary_data.keys())

msg  = "  Successfully exported schedules ✅\n"
msg += "\n  Total schedules exported 📦: {}\n".format(len(names))
msg += "\n  Schedules exported 📃:\n"
msg += "\n".join("    - {}".format(x) for x in names)

Alert(msg, title="OMBIM-AUTOMATION", header="Export Complete", exit=False)