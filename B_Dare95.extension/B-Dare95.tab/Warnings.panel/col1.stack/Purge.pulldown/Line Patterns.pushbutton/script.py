# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes line patterns that no line style, object style, override or type uses. It is Revit's own Purge Unused rule, with a clear list.
__________________________________________________
How-to:

-> Click on the button
-> Read the list of unused line patterns: they are all checked
-> Uncheck anything you want to keep
-> Check Show used items too to see what stays and why
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "line_patterns")  # noqa: F821
