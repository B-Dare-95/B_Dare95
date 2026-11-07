# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Lists the sheets with nothing on them, so you can delete the ones you don't need. Nothing is ticked for you, because an empty sheet can be a placeholder in a sheet list.
__________________________________________________
How-to:

-> Click on the button
-> Read the list: nothing is ticked for you, so tick what to delete
-> Tick Show used items too to see what stays and why
-> Leave "Purge up to 3 times" ticked to also purge what this purge frees
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "sheets")  # noqa: F821
