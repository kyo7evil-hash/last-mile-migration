# Last Mile Migration Checklist

A shared web checklist for the Last Mile laptops: Windows 11 update, returns, replacements and Snipe-IT clean-up. The team opens one link, signs in with their company Google account, and everyone sees the same ticks live (updates appear within about 5 seconds).

## Using the page

**Summary tab (main screen)**
- **Laptops complete:** a laptop counts as complete when all 4 steps are Done or N/A.
- **Progress by step:** click a step to see the laptops still waiting on it.
- **Progress by region:** the least finished regions are listed first. Click a region to open its laptops.

**Checklist tab**
- Each laptop is its own card, showing:
  - a status badge: **Not started**, **In progress** or **Complete**;
  - its user, laptop and serial;
  - tick boxes for the 4 steps: **Return to IT → Replacement to hub → Win 11 updated → Snipe-IT updated**.
- Click a tick box to change it: **empty (Pending) → ✓ (Done) → dashed – (Not needed) → empty**. It saves straight away.
- Steps marked "Not needed" don't count against progress, so "1 of 3 done" means one step is not needed.
- Click **Details & notes →** on a card to edit **Latest user**, **Remarks** and the **Replacement laptop** fields (new serial, new tag, ISD ticket, TN). Then press **Save changes**.
- **Search** looks across tag, serial, users, hub and ticket.
- You can also filter by **region** and **hub**, and switch between **Not complete / Complete / All**.
- **Sort by** offers: region then hub, hub, least done first, most done first, tag number, or recently changed. Each person's sort choice is remembered.
- **Download Excel** saves the current view, including who made the last change and when.

## How the Excel was loaded

The data comes from `Last Mile windows 11 migration.xlsx`:
- **Sheet1** is the laptop list.
- **LM** holds the replacement details, matched to Sheet1 by tag.

| Excel | Becomes |
|---|---|
| Ticked (TRUE / 1) | Done |
| Unticked or blank | Pending |
| Remarks say "no need replacement" | Replacement to hub = N/A |
| Snipe-IT updated (new step) | Pending for every laptop |

Changes made on the web are kept per laptop tag, and they always win over the Excel values.

## Who can do what

| Person | Can do |
|---|---|
| Anyone signed in with a company Google account | View and update the checklist |
| Admins (`ADMIN_EMAILS` setting) | Also **Upload workbook** to load or replace the laptop list |

## Hosting (Substrait)

The app runs the same way as the Windows 11 tracker.

| File | What it is |
|---|---|
| `lastmile-checklist.html` | The page itself |
| `frontend/claude-shim.js` | Connects the page to the app's database |
| `backend/main.py` | Small data store, with Google sign-in checks |
| `cicd/`, `substrait.yaml`, `backend/resources/db/migration/` | Deploy setup, including the database |
| `dev/devserver.py` | Local test server only. It is not used online. |

**First-time setup**
1. Link a new app with `/substrait:link`, then deploy with `/substrait:deploy`.
2. In the Substrait portal:
   - Turn on **Google SSO** (Access tab).
   - Check that **ADMIN_EMAILS** is `sanusi.othman@ninjavan.co`.
3. Open the app link, go to the **Checklist** tab, click **Upload workbook** and pick the Excel file. You only need to do this once.
4. Share the link with the team.

The Excel and CSV files are never uploaded with the code, because they contain staff emails.
