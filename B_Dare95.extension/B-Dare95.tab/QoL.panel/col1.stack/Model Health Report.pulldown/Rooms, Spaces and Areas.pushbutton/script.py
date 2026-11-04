# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Reports rooms, spaces and areas with their number, name, level and area: unplaced, redundant or not enclosed, numbers used more than once, and the areas in each area scheme.
This is the "Rooms, Spaces and Areas" part of the Model Health Check. Pass / fail checks flag problems; the others count and list what is in the model. Nothing in the model is changed. The window stays open while you work.
__________________________________________________
How-to:

-> Open the model you want to check
-> Click on the button and wait for the checks to finish
-> Click a check to select its elements in the model, or its arrow to see the list
-> Click a room, space or area in a list to select it; click a duplicate number to select the ones using it
-> Ctrl+click adds to the current selection; tick Failed only to see the problems
-> Click Refresh after changing the model
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

from bd_health_window import show_section_report

show_section_report(__revit__, u"Rooms, Spaces and Areas")
