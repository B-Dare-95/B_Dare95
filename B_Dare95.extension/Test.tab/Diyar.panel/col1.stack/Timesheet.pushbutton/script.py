import clr
clr.AddReference("System")

from System.Diagnostics import Process, ProcessStartInfo

url = "https://diyar.deltekfirst.com/diyar/app/#!Timekeeper/view/0/0/6364%7C2026-01-31%7CEDC/presentation"

psi = ProcessStartInfo(url)
psi.UseShellExecute = True
Process.Start(psi)