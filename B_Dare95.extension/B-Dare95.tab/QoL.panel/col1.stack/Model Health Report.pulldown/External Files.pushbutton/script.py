# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Reports the linked and imported files: Revit links and their link method, unpinned links, linked CAD (and those visible in all views or unpinned), imported CAD, imported SketchUp files and raster images.
This is the "External Files" part of the Model Health Check. Pass / fail checks flag problems; the others count and list what is in the model. Nothing in the model is changed. The window stays open while you work.
__________________________________________________
How-to:

-> Open the model you want to check
-> Click on the button and wait for the checks to finish
-> Click a check to select its elements in the model, or its arrow to see the list
-> Click an unpinned link or a CAD file to select it in the model
-> Ctrl+click adds to the current selection; check Failed only to see the problems
-> Click Refresh after changing the model
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

from bd_health_window import show_section_report

show_section_report(__revit__, u"External Files")
