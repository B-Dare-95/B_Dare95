__doc__ = """__________________________________________________
Description:

Opens the B-Dare95 online user guide in your web browser, with step-by-step help for every tool in the extension.
__________________________________________________
How-to:

-> Click on the button
-> The user guide opens in your default web browser
-> Find the tool you need by its panel and name
__________________________________________________
Author: Mohamed Bedair"""

import clr
clr.AddReference("System")

from System.Diagnostics import Process, ProcessStartInfo

url = "https://bdare95userguide.notion.site/B-Dare95-User-Guide-bd47c405234640869ce2fbbf9e1204ff"

psi = ProcessStartInfo(url)
psi.UseShellExecute = True
Process.Start(psi)