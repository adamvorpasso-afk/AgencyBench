# Solar Lead Agent

An AI agent that searches the web for **businesses and organisations** that would be good prospects for solar panels, then saves them to a spreadsheet.

## How it works (the simple version)

1. You tell it where to look, e.g. `Leeds, UK`.
2. Claude searches the web for places with big roofs and high power bills: warehouses, factories, farms, schools, supermarkets, and cold stores. It also looks for companies with net-zero pledges, new building projects, and open solar tenders.
3. It checks each place against a real web page and gives it a score from 1 to 10.
4. You get `leads/leads.csv` (opens in Excel or Google Sheets) and `leads/leads.json`.

## Setup

```bash
cd solar-lead-agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
python agent.py --area "Leeds, UK" --count 15
python agent.py --area "West Yorkshire" --segment "farms and agricultural buildings" --count 20
python agent.py --area "Phoenix, AZ" --segment "warehouses" --out leads/phoenix
```

| Flag | Meaning |
|---|---|
| `--area` | Where to search (required) |
| `--count` | How many leads to aim for (default 15) |
| `--segment` | Optional focus, e.g. `schools`, `car dealerships`, `cold storage` |
| `--out` | Output path prefix (default `leads/leads`) |

## Output columns

`organisation, category, address, website, contact, fit_signals, estimated_roof_or_site, score, pitch_angle, source_urls`

Leads are sorted by score, best first.

## Guardrails built in

- **Businesses only.** The agent will not collect data on homeowners or other private individuals.
- **Published business contacts only.** It uses switchboards, general emails, contact pages, and role holders the company lists publicly.
- **Sources required.** A lead with no source URL is rejected, and Claude is told to leave a field blank rather than guess.
- **Duplicates merged.** Organisation names are compared with case and spacing ignored.
- **Cost cap.** Each run stops after 40 agent turns, 30 web searches, and 20 page fetches. Change `MAX_TURNS` or the `max_uses` values in `agent.py` to raise the cap.

## Before you call or email anyone

- **UK:** B2B calls must be screened against the Corporate TPS. B2B email marketing to corporate addresses is allowed under PECR if you include an opt-out, but GDPR still applies to any named person.
- **US:** Follow the TCPA and state rules for cold calls, and CAN-SPAM for email.
- **Verify every lead yourself.** The agent can misread a page. For example, a roof that looks "empty" may already be leased for solar, or the business may rent the building.
