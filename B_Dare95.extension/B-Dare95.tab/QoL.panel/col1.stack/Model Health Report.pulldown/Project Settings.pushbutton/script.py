# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Reports the model's settings: Revit version, design options, elements per phase, worksets, Project Information, survey point and project base point coordinates, browser organization and the volume computation setting.
This is the "Project Settings" part of the Model Health Check. Pass / fail checks flag problems; the others count and list what is in the model. Nothing in the model is changed. The window stays open while you work.
__________________________________________________
How-to:

-> Open the model you want to check
-> Click on the button and wait for the checks to finish
-> Click a check to select its elements in the model, or its arrow to see the list
-> Expand a check to see its list, e.g. every Project Information parameter and its value
-> Ctrl+click adds to the current selection; check Failed only to see the problems
-> Click Refresh after changing the model
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

from bd_health_window import show_section_report

show_section_report(__revit__, u"Project Settings")
