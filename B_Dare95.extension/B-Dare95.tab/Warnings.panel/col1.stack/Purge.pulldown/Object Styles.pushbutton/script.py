# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes subcategories (object styles) that no loaded family defines, no type points to and no loaded link uses. It opens every family first to read their subcategories, so it takes a while on big projects. Categories with in-place families are left alone.
__________________________________________________
How-to:

-> Click on the button
-> Read the list of unused object styles: they are all checked
-> Uncheck anything you want to keep
-> Check Show used items too to see what stays and why
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "object_styles")  # noqa: F821
