# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Reports the things that build up while a model is worked on and slow it down: file size, warnings, loadable and in-place families, purgeable elements, imported object styles, and model and detail groups.
This is the "Model Performance" part of the Model Health Check. Pass / fail checks flag problems; the others count and list what is in the model. Nothing in the model is changed. The window stays open while you work.
__________________________________________________
How-to:

-> Open the model you want to check
-> Click on the button and wait for the checks to finish
-> Click a check to select its elements in the model, or its arrow to see the list
-> Click Warnings to select every element that has a warning, or a group check to select the groups
-> Ctrl+click adds to the current selection; tick Failed only to see the problems
-> Click Refresh after changing the model
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

from bd_health_window import show_section_report

show_section_report(__revit__, u"Model Performance")
