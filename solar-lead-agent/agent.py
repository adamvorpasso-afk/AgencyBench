#!/usr/bin/env python3
"""Solar lead finder agent.

Claude searches the public web for organisations in a target area that look
like good prospects for a solar installation (big roofs, high energy use,
sustainability pledges, new builds, open tenders), and records each one via a
`save_lead` tool. Results are written to JSON and CSV.

Usage:
    export ANTHROPIC_API_KEY=...
    python agent.py --area "Leeds, UK" --count 15
    python agent.py --area "Phoenix, AZ" --segment "warehouses and logistics" --count 25
"""

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
MAX_TURNS = 40  # hard stop for the agent loop (tool rounds + pause_turn resumes)

SYSTEM_PROMPT = """You are a B2B lead researcher for a solar installation company.

Your job: find real organisations in the target area that are strong prospects for
rooftop or ground-mount solar, verify them with web sources, and record each one by
calling the `save_lead` tool exactly once per organisation.

Good lead signals (the more, the better the score):
- Large flat or low-pitch roofs: warehouses, distribution centres, factories, cold
  storage, retail parks, supermarkets, car dealerships, schools, colleges, hospitals,
  leisure centres, farms with large barns.
- High daytime electricity use: manufacturing, food processing, data centres,
  refrigeration, hotels, care homes.
- Public sustainability / net-zero commitments, ESG reports, carbon-reduction plans.
- Recent planning applications, new builds, expansions, or roof refurbishments.
- Open tenders / RFPs / frameworks for solar PV or energy efficiency.
- Owner-occupied premises (the decision-maker controls the roof).

Rules:
- Organisations only. Never collect personal data about private individuals or
  homeowners (no personal phone numbers, home addresses, or personal emails).
- Contact details must be published business channels: a main switchboard, a
  general or sales/facilities email, or a contact page URL. If a named contact is
  publicly listed in an official business capacity (e.g. "Head of Facilities" on the
  company site), you may include name + title only.
- Every lead must cite at least one source URL you actually looked at. Do not invent
  facts, addresses, or contacts; leave a field empty rather than guess.
- Skip organisations that already clearly have a large solar array installed, unless
  there is evidence of expansion.
- Prefer quality over quantity. Score honestly (1 = weak, 10 = outstanding).

When you have saved the requested number of leads (or exhausted good options),
finish with a short plain-text summary of what you found and any patterns worth
following up (e.g. "three industrial estates with many owner-occupied units")."""

SAVE_LEAD_TOOL = {
    "name": "save_lead",
    "description": (
        "Record one verified solar sales lead. Call once per organisation, only "
        "after you have checked at least one source about it."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "organisation", "category", "address", "website", "contact",
            "fit_signals", "estimated_roof_or_site", "score", "pitch_angle",
            "source_urls",
        ],
        "properties": {
            "organisation": {"type": "string", "description": "Legal or trading name."},
            "category": {
                "type": "string",
                "enum": [
                    "industrial", "warehouse_logistics", "retail", "agriculture",
                    "education", "healthcare", "hospitality", "public_sector",
                    "commercial_office", "tender_rfp", "developer_new_build", "other",
                ],
            },
            "address": {"type": "string", "description": "Business/site address, or empty if unknown."},
            "website": {"type": "string", "description": "Organisation website, or empty."},
            "contact": {
                "type": "string",
                "description": "Published business contact: switchboard, generic email, contact page URL, and/or a publicly listed role holder (name + title). Empty if none found.",
            },
            "fit_signals": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete evidence this is a good solar prospect.",
            },
            "estimated_roof_or_site": {
                "type": "string",
                "description": "Rough size description if known (e.g. '~12,000 m2 warehouse roof'), else empty.",
            },
            "score": {"type": "integer", "description": "Lead quality 1-10."},
            "pitch_angle": {
                "type": "string",
                "description": "One or two sentences on how a salesperson should open the conversation.",
            },
            "source_urls": {"type": "array", "items": {"type": "string"}},
        },
    },
}

TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 30},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 20},
    SAVE_LEAD_TOOL,
]


def lead_key(lead: dict) -> str:
    return " ".join(lead["organisation"].lower().split())


def validate_lead(lead: dict) -> str | None:
    """Return an error message if the lead is unusable, else None."""
    if not lead.get("organisation", "").strip():
        return "organisation is empty"
    if not lead.get("source_urls"):
        return "at least one source URL is required"
    if not 1 <= lead.get("score", 0) <= 10:
        return "score must be between 1 and 10"
    return None


def run_agent(area: str, count: int, segment: str | None) -> tuple[list[dict], str]:
    client = anthropic.Anthropic()
    leads: dict[str, dict] = {}

    task = f"Find {count} solar leads in: {area}."
    if segment:
        task += f" Focus on this segment: {segment}."
    task += f" Today's date is {date.today().isoformat()}."

    messages: list[dict] = [{"role": "user", "content": task}]
    summary = ""

    for turn in range(MAX_TURNS):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        messages.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if block.type == "server_tool_use":
                query = block.input.get("query") or block.input.get("url") or ""
                print(f"  [{block.name}] {query}", file=sys.stderr)

        if response.stop_reason == "refusal":
            print("Model declined to continue.", file=sys.stderr)
            break

        if response.stop_reason == "pause_turn":
            # Server-side search loop hit its iteration cap; resend to resume.
            continue

        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name != "save_lead":
                    results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": f"Unknown tool {block.name}", "is_error": True,
                    })
                    continue
                lead = dict(block.input)
                error = validate_lead(lead)
                if error:
                    results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": f"Rejected: {error}", "is_error": True,
                    })
                    continue
                key = lead_key(lead)
                duplicate = key in leads
                leads[key] = lead
                print(f"  + lead {len(leads)}: {lead['organisation']} (score {lead['score']})", file=sys.stderr)
                note = "Updated existing lead." if duplicate else "Saved."
                results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": f"{note} {len(leads)}/{count} leads collected.",
                })
            messages.append({"role": "user", "content": results})
            continue

        # end_turn or max_tokens: collect the final summary and stop.
        summary = "\n".join(b.text for b in response.content if b.type == "text")
        break
    else:
        print(f"Stopped after {MAX_TURNS} turns.", file=sys.stderr)

    ranked = sorted(leads.values(), key=lambda l: l["score"], reverse=True)
    return ranked, summary


def write_outputs(leads: list[dict], out_prefix: Path) -> None:
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_prefix.with_suffix(".json")
    csv_path = out_prefix.with_suffix(".csv")

    json_path.write_text(json.dumps(leads, indent=2, ensure_ascii=False))

    fields = list(SAVE_LEAD_TOOL["input_schema"]["properties"])
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for lead in leads:
            row = dict(lead)
            row["fit_signals"] = "; ".join(lead["fit_signals"])
            row["source_urls"] = " ".join(lead["source_urls"])
            writer.writerow(row)

    print(f"Wrote {len(leads)} leads to {json_path} and {csv_path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Find B2B solar leads with Claude + web search.")
    parser.add_argument("--area", required=True, help='Target area, e.g. "Leeds, UK" or "Austin, TX".')
    parser.add_argument("--count", type=int, default=15, help="How many leads to aim for.")
    parser.add_argument("--segment", help='Optional focus, e.g. "farms", "schools", "warehouses".')
    parser.add_argument("--out", default="leads/leads", help="Output path prefix (no extension).")
    args = parser.parse_args()

    print(f"Searching for {args.count} solar leads in {args.area}...", file=sys.stderr)
    leads, summary = run_agent(args.area, args.count, args.segment)
    write_outputs(leads, Path(args.out))
    if summary:
        print("\n" + summary)


if __name__ == "__main__":
    main()
