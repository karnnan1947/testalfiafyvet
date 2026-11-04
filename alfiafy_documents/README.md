# Alfiafy Regulatory Compliance & License Expiry Alerts (`alfiafy_documents`, DES00141)

BRD 1.7 customization #2 (Odoo 20): pharmacy licenses and doctors' /
practitioners' licenses are stored in Odoo Documents with an expiry date, and
management is alerted before they expire.

Depends on `documents`, `hr`, `stock`, `mail`, `alfiafy_product_base`.

| Area | What it does |
|---|---|
| License fields | On `documents.document`: Regulatory License (flag), License Type (Pharmacy License, Doctor / Practitioner License, Commercial Registration (CR), Vehicle Permit, Other), License Number, Issuing Authority, Branch (warehouse), Doctor / Employee, Issue Date, Expiry Date, Alert Days Before Expiry (default 60). |
| Status | Days to Expiry (negative once expired) and Expiry Status: Valid, Expiring Soon (inside the alert window), Expired. The status is stored and refreshed every night by the scheduled action. |
| Screens | Documents > **Regulatory Licenses**: kanban by expiry status, list, license form (file, folder, tags, "License & Regulatory Details", chatter). In the Documents app: filters Regulatory Licenses / Expiring Soon / Expired, group by Expiry Status, status badge on license cards. |
| Alerts | Scheduled action "Documents: License Expiry Alerts" (daily): for each license with days to expiry <= alert days, a To-Do activity ("License expiry reminder") for every compliance manager and the e-mail "[URGENT] License Expiry Alert". Nothing is sent again while a reminder is still open; once it is marked done, the next run reminds again. |
| Settings | Documents > Configuration > Settings > Regulatory Compliance > **Compliance Alert Recipients** (per company). Without recipients, no alert is created (a warning is logged). |

Odoo 20 Documents has no full form view for documents (the app uses a preview
and a details panel), so the license fields are edited in the module's own form
(Documents > Regulatory Licenses, or from the alert e-mail link).

Tests: `--test-tags /alfiafy_documents`.
