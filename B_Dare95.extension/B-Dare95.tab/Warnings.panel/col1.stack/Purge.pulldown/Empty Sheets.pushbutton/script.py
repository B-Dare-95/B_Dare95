# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Lists the sheets with nothing on them, so you can delete the ones you don't need. Nothing is checked for you, because an empty sheet can be a placeholder in a sheet list.
__________________________________________________
How-to:

-> Click on the button
-> Read the list: nothing is checked for you, so check what to delete
-> Check Show used items too to see what stays and why
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "sheets")  # noqa: F821
