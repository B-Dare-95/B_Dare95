# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Reports levels and grids: their types, elements that don't belong on the Shared Levels and Grids workset, and levels and grids on the wrong workset.
Rooms, spaces and areas have their own report: Rooms, Spaces and Areas.
This is the "Datum and Location Elements" part of the Model Health Check. Pass / fail checks flag problems; the others count and list what is in the model. Nothing in the model is changed. The window stays open while you work.
__________________________________________________
How-to:

-> Open the model you want to check
-> Click on the button and wait for the checks to finish
-> Click a check to select its elements in the model, or its arrow to see the list
-> Click Levels or Grids to select them all, or a level or grid type to select the ones using it
-> Ctrl+click adds to the current selection; check Failed only to see the problems
-> Click Refresh after changing the model
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

from bd_health_window import show_section_report

show_section_report(__revit__, u"Datum and Location Elements")
