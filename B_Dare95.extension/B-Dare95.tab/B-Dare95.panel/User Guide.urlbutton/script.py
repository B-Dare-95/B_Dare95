import clr
clr.AddReference("System")

from System.Diagnostics import Process, ProcessStartInfo

url = "https://brave-spandex-ba3.notion.site/B-Dare95-Tools-bd47c405234640869ce2fbbf9e1204ff"

psi = ProcessStartInfo(url)
psi.UseShellExecute = True
Process.Start(psi)