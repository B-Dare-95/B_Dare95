# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes the CAD imports, CAD links and PDFs you check, not only unused ones, plus CAD links that aren't placed. When every placed copy of a file is checked, the file itself is removed too. Nothing is checked for you.
__________________________________________________
How-to:

-> Click on the button
-> Read the list: nothing is checked for you, so check what to delete
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "cad_and_pdf")  # noqa: F821
