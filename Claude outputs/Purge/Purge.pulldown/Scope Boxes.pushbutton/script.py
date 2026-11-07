# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes scope boxes that no view crop and no level, grid or reference plane is assigned to.
__________________________________________________
How-to:

-> Click on the button
-> Read the list of unused scope boxes: they are all ticked
-> Untick anything you want to keep
-> Tick Show used items too to see what stays and why
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "scope_boxes")  # noqa: F821
