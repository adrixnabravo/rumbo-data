# Rumbo Data

Public records of the **Los Angeles County Metropolitan Transportation Authority (Metro) Board of Directors**, downloaded nightly and saved as plain CSV files so anyone can check [Rumbo](#about)'s numbers.

Source: Metro's official board records system, through the public [Legistar Web API](https://webapi.legistar.com/v1/metro/matters). The same records power [boardagendas.metro.net](https://boardagendas.metro.net/).

## What's here

| File | One row per | What it tells you |
| --- | --- | --- |
| `data/events/YYYY.csv` | meeting | Every board, committee and service council meeting, with links to agendas, minutes and video |
| `data/items/YYYY.csv` | agenda item at a meeting | What was on the agenda, its file number, the action taken, mover and seconder |
| `data/votes/YYYY.csv` | person per voted item | How each member voted: Aye, Nay, Abstain, Absent, Recused |
| `data/rollcalls/YYYY.csv` | person per roll call | Who was present when the meeting was called to order |
| `data/matters/YYYY.csv` | board report | Every report and motion by file number (like `2026-0689`), type and status |
| `data/persons.csv` | person | Everyone in the records system |
| `data/memberships.csv` | person per body | Who sat on which board or committee, and when |
| `data/bodies.csv` | body | The board, committees, service councils and other bodies |
| `data/last_updated.json` | — | When the data was last pulled |

Test meetings and duplicate Spanish-audio meeting entries (marked `(SAP)` in the source) are left out.

## How it updates

- **Every night** a GitHub Action refreshes the last 120 days, so new votes and corrected minutes show up within a day.
- **History** going back to 2015 was loaded once with the *Backfill history* action. It can be re-run anytime.

## Caveats

- These are Metro's own records, unedited. If Metro's records are wrong, these are wrong. Report it and we'll note it.
- Minutes are marked *Draft* until the board approves them, usually at the next meeting. Recent votes can change.
- A member can be present at roll call and leave before a vote. Count attendance from votes, not just roll calls, when it matters.

## About

Rumbo is an independent data journalism project about LA transit: where the money goes, who decides, and how riders can take part. Not affiliated with LA Metro.
