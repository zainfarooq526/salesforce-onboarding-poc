# 5-minute customer demo script

**Audience:** a sales-ops or RevOps lead who onboards lead lists into Salesforce today with spreadsheets and Data Loader.
**Setup:** app running (`docker compose up`), browser at http://localhost:8000, `docs/architecture.png` open in a second tab.

## Requirements and the business value they deliver

| # | Requirement | How the POC delivers it | Business value |
|---|---|---|---|
| R1 | Self-serve CSV import | Drag-and-drop upload; handles any export (encoding, comma/semicolon/tab) | Ops can onboard a list in minutes without an admin or Data Loader |
| R2 | Field mapping | Headers auto-mapped to Lead fields (`E-mail Address` → Email), editable, required fields checked | No renaming columns by hand; fewer mapping mistakes |
| R3 | Data quality | Names, emails, phones (E.164), websites and headcounts normalized; bad rows rejected with a reason and exported as a CSV | Clean CRM data; only the broken rows need human attention |
| R4 | Dedupe | Duplicates inside the file are caught (email, or name + company) and merged so no field is lost | No double outreach to the same person; trustworthy pipeline reports |
| R5 | Sync via REST API | Existing Leads matched with SOQL and updated; new ones created; 200 records per call; every row stores its Salesforce Id | Safe to re-run (no duplicates), light on API limits, full audit trail |

## Script

### 0:00 – 0:30 · The problem
> "Today, every new lead list means renaming columns, cleaning data in Excel, and running Data Loader, and
> duplicates still slip in. This proof of concept turns that into a four-step flow anyone on your team can run."

Show the upload screen. Point at the **Mock / Live Salesforce org** badge.

### 0:30 – 1:15 · Upload (R1)
Click **Use the sample file**: 24 leads exported from a trade-show tool, with messy casing, five phone formats,
a duplicate person, and a couple of broken rows.
> "No template needed. It reads whatever your tools export."

### 1:15 – 2:15 · Map fields (R2)
Show the mapping table. Every column was matched automatically, marked **auto**.
> "`E-mail Address` became Email and `Phone #` became Phone. If something's wrong, change the dropdown.
> It won't let you continue until Last Name and Company, the two fields Salesforce requires on a Lead, are mapped."

Briefly set a column to "Don't import" and back to show it's editable.

### 2:15 – 3:30 · Review and dedupe (R3, R4)
Click **Validate & find duplicates**. Walk the four numbers: 24 rows, 19 ready, 2 duplicates merged, 3 need fixing.
- **Ready** tab: names fixed (`JAMES O'NEILL` → `James O'Neill`), emails lower-cased.
- **Duplicates** tab: row 8 is Aisha Khan again with a different email case. It was merged into row 1.
  > "Your reps won't call the same person twice."
- **Invalid** tab: `liam.murphy@clearwave` has no domain; Grace Lee has no company.
  > "These don't block the other 19. Download the exceptions CSV, fix them, and re-upload."

### 3:30 – 4:30 · Sync (R5)
Click **Sync 19 records**. Result: **17 created, 2 updated**.
> "Maria Gonzalez and Tom Becker were already in Salesforce, so we updated them instead of creating duplicates.
> Every row now has its Salesforce Id."

Optional: run the same file again from the history panel to show **0 created, 19 updated**.

### 4:30 – 5:00 · Architecture and proof
Switch to `docs/architecture.png`. React front end, Flask API, PostgreSQL staging tables, Salesforce REST API
with OAuth client credentials.
> "We tested it on 100 records against 5 criteria: mapping, validation, dedupe, sync accuracy, and re-run
> safety. All five pass, and the report is in the repo. Next step would be pointing it at your sandbox org."

## Likely questions

- **Other objects (Contacts, Accounts)?** The field list lives in one module (`backend/app/fields.py`); a new
  object is a new field list plus its match rule.
- **Large files?** The POC caps at 10,000 rows. Beyond that, switch the sync step to the Bulk API 2.0.
- **Security?** OAuth client credentials with a dedicated integration user. No passwords stored; secrets come
  from environment variables.
