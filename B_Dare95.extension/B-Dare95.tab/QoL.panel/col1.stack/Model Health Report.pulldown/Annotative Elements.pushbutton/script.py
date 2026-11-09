# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Reports text and dimension styles, line patterns and styles, fill patterns, filled regions, elevation and section tags, matchlines, view references, keynotes and the totals of detail lines and annotation elements.
This is the "Annotative Elements" part of the Model Health Check. Pass / fail checks flag problems; the others count and list what is in the model. Nothing in the model is changed. The window stays open while you work.
__________________________________________________
How-to:

-> Open the model you want to check
-> Click on the button and wait for the checks to finish
-> Click a check to select its elements in the model, or its arrow to see the list
-> Click a keynote value to select the keynote tags that use it
-> Ctrl+click adds to the current selection; check Failed only to see the problems
-> Click Refresh after changing the model
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

from bd_health_window import show_section_report

show_section_report(__revit__, u"Annotative Elements")
