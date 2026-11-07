# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes filled region types that no filled region uses. It is Revit's own Purge Unused rule, with a clear list.
__________________________________________________
How-to:

-> Click on the button
-> Read the list of unused filled region types: they are all ticked
-> Untick anything you want to keep
-> Tick Show used items too to see what stays and why
-> Leave "Purge up to 3 times" ticked to also purge what this purge frees
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "filled_region_types")  # noqa: F821
