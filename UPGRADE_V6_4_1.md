# Assam MDM Dashboard V6.4.1 — Correct Reported / Not Reported Logic

Fixes the V6.4 filtering bug.

For District / Block / Cluster:
- Reported Excel = `Reported Schools > 0`
- Not Reported Excel = `Not Reported Schools > 0`

Therefore a partially reporting District/Block/Cluster can correctly appear in both workbooks.

For School:
- Reported Excel = Daily Status Yes
- Not Reported Excel = Daily Status No

Important data-availability limitation remains:
- Historical District counts are available from the previous-date public source.
- Historical Block/Cluster rows require a tracker snapshot for that date.
- Historical School names require a school-level capture/cache for that date.
