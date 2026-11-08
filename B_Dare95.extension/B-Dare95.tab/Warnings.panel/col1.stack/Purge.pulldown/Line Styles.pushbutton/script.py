# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes line styles that no line in the model uses and no type points to. Revit's own styles are never listed. Each style is deleted on its own and put back if anything else would go with it.
__________________________________________________
How-to:

-> Click on the button
-> Read the list of unused line styles: they are all ticked
-> Untick anything you want to keep
-> Tick Show used items too to see what stays and why
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "line_styles")  # noqa: F821
