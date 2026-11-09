# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Reports views, schedules, sheets and placeholder sheets, view templates, views with hidden elements, views with no template or not on a sheet, the Navisworks export view, legends and scope boxes.
This is the "Views" part of the Model Health Check. Pass / fail checks flag problems; the others count and list what is in the model. Nothing in the model is changed. The window stays open while you work.
__________________________________________________
How-to:

-> Open the model you want to check
-> Click on the button and wait for the checks to finish
-> Click a check to select its elements in the model, or its arrow to see the list
-> Expand Views, Schedules, Sheets or Placeholder Sheets to list them
-> Click a view, sheet or schedule to select it; double-click it or click Open to open it
-> Ctrl+click adds to the current selection; check Failed only to see the problems
-> Click Refresh after changing the model
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

from bd_health_window import show_section_report

show_section_report(__revit__, u"Views")
