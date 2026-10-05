"""Solar closer gig finder.

An agent that searches the web for solar (and solar + battery) sales closer
gigs, reads each posting, and ranks them for someone who is new to the
industry. It is deliberately skeptical: many "closer" listings are really
unpaid-training door-knocking setter roles, and many "remote" listings are
field jobs.

Usage:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...          # or `ant auth login`
    python solar_closer_agent.py --location "Phoenix, AZ" --remote-ok
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

import anthropic

MODEL = "claude-opus-5-5"
MAX_CONTINUATIONS = 8  # server tools can pause long turns; resume at most this many times

SYSTEM_PROMPT = """\
You are a job-search agent for someone who wants to work as a residential solar
sales CLOSER (solar panels, and ideally home batteries / storage too) but is
relatively new to the solar industry.

## How to work
1. Search broadly: job boards (Indeed, ZipRecruiter, LinkedIn, Glassdoor),
   installer and dealer career pages, and solar-sales recruiting pages. Use
   several phrasings: "solar closer", "solar energy consultant", "solar sales
   consultant", "solar + battery sales", "energy storage sales rep",
   "solar sales representative entry level", "virtual solar closer".
2. Open the actual posting (web_fetch) before you rank anything. Titles lie.
3. Keep only postings from roughly the last 45 days that you could actually open.
   Never invent a listing, company, pay figure, or URL.

## What "good for a newcomer" means (score 1-10)
Score higher when the posting shows:
- Paid training, a base / draw / hourly component, or a paid ramp period.
- Pre-set or company-generated appointments (a setter team or marketing leads),
  so the closer is not self-generating every lead from day one.
- Battery / storage in the product line (a growth skill worth learning).
- A real installer or established dealer, not an anonymous "partner" network.
- Clear commission structure (per-kW, per-deal, or % with numbers).
- W-2 or clearly explained 1099 terms; stated clawback/chargeback policy.

Score lower (and say why) when you see:
- "Closer" in the title but the duties are door-knocking / setting appointments.
- "Remote" in the location but the duties require driving to homes or canvassing.
- Commission-only with no training pay AND "experienced closers only".
- Pay ranges that are implausibly wide (e.g. $60k-$290k) or "average $2,500/week"
  claims with no basis.
- Company name unrelated to solar, no website, or a recruiter that hides the
  installer's identity.

## Hard red flags (list separately, never recommend)
- Asking the applicant to pay for training, licenses, leads, or a "starter kit".
- MLM / recruit-your-own-downline structures.
- Requests for SSN/bank details before an interview.

## Output (Markdown only)
Start with a one-paragraph summary of the market you saw.
Then a table of the top matches, best first:
| Score | Role (linked to the posting) | Company | Location / remote? | Pay structure | Appointments provided? | Batteries? | Why it fits a newcomer |
Then a "Watch out" section for listings that looked attractive but are
mislabeled or risky, and a "Red flags" section for anything to avoid.
Finish with 3-5 practical next steps for a newcomer (e.g. which to apply to
first, what to ask in the interview: clawbacks, lead source, install timelines,
who pays for cancelled deals, how batteries are compensated).
"""


def build_request(args: argparse.Namespace) -> str:
    where = args.location or "anywhere in the United States"
    remote = "Remote / virtual closer roles are welcome." if args.remote_ok else "Prefer in-person or hybrid roles near that location."
    extra = f"\nAdditional preferences: {args.notes}" if args.notes else ""
    return (
        f"Today is {dt.date.today():%B %d, %Y}.\n"
        f"Find up to {args.max_results} solar closer gigs for me. Location: {where}. {remote}\n"
        "I'm relatively new to solar panels and batteries, so rank by how well each role "
        "sets up a beginner to succeed, not just by the headline pay."
        f"{extra}"
    )


def run_agent(args: argparse.Namespace) -> str:
    client = anthropic.Anthropic()

    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": args.max_searches},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": args.max_searches * 2},
    ]
    if args.location:
        city, _, region = (part.strip() for part in args.location.partition(","))
        tools[0]["user_location"] = {"type": "approximate", "city": city, "country": "US"}
        if region:
            tools[0]["user_location"]["region"] = region

    messages: list = [{"role": "user", "content": build_request(args)}]

    for _ in range(MAX_CONTINUATIONS + 1):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            output_config={"effort": args.effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for event in stream:
                if event.type == "content_block_start" and getattr(event.content_block, "type", "") == "server_tool_use":
                    print(f"  … {event.content_block.name}", file=sys.stderr, flush=True)
            response = stream.get_final_message()

        if response.stop_reason == "pause_turn":
            # Long server-tool turn: hand the partial turn back so the model continues.
            messages.append({"role": "assistant", "content": response.content})
            continue
        if response.stop_reason == "refusal":
            raise RuntimeError(f"Request declined: {response.stop_details}")
        return "\n".join(b.text for b in response.content if b.type == "text").strip()

    raise RuntimeError("Agent did not finish within the continuation limit.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Find beginner-friendly solar closer gigs.")
    parser.add_argument("--location", help='City/state to search around, e.g. "Tampa, FL"')
    parser.add_argument("--remote-ok", action="store_true", help="Include remote/virtual closer roles")
    parser.add_argument("--notes", help='Extra preferences, e.g. "W-2 only, no door knocking"')
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--max-searches", type=int, default=12)
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--out", default=None, help="Write the report to this Markdown file")
    args = parser.parse_args()

    try:
        report = run_agent(args)
    except anthropic.AuthenticationError:
        sys.exit("Authentication failed: set ANTHROPIC_API_KEY or run `ant auth login`.")
    except anthropic.RateLimitError:
        sys.exit("Rate limited by the API; try again in a minute.")
    except anthropic.APIConnectionError:
        sys.exit("Network error reaching the Anthropic API.")

    out = pathlib.Path(args.out or f"solar_gigs_{dt.date.today():%Y-%m-%d}.md")
    out.write_text(report + "\n")
    print(report)
    print(f"\nSaved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
