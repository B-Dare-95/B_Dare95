# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes materials that no element, type, family or other material uses. It is Revit's own Purge Unused rule; a material's appearance assets go with it when nothing else uses them.
__________________________________________________
How-to:

-> Click on the button
-> Read the list of unused materials: they are all ticked
-> Untick anything you want to keep
-> Tick Show used items too to see what stays and why
-> Leave "Purge up to 3 times" ticked to also purge what this purge frees
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "materials")  # noqa: F821
