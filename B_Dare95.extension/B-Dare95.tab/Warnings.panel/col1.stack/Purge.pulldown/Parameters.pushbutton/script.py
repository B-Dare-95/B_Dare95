# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes project, shared and global parameters that nothing uses: no element or type has a value in them and no schedule or view filter uses them. Shared parameters that only families carry are never listed, because they come back with those families.
__________________________________________________
How-to:

-> Click on the button
-> Read the list of unused project, shared and global parameters: they are all checked
-> Uncheck anything you want to keep
-> Check Show used items too to see what stays and why
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "parameters")  # noqa: F821
