"""Solar closer gig finder.

An agent that searches the web for REMOTE residential solar (and solar +
battery) sales closer gigs, reads each posting, and ranks them for someone who
is new to the solar industry but already has some sales or product knowledge
and learns fast. Australia is the default market; the US is also supported.

It is deliberately skeptical: many "closer" listings are really door-knocking
setter roles, many "remote" listings are field jobs, and some "remote" roles
quietly require living in one state.

Usage:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...          # or `ant auth login`
    python solar_closer_agent.py                                # Australia, remote
    python solar_closer_agent.py --location "Brisbane, QLD"
    python solar_closer_agent.py --country US --location "Phoenix, AZ"
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
You are a job-search agent for someone who wants to work REMOTELY as a
residential solar sales CLOSER (solar panels, and ideally home batteries).

## The candidate
New to the solar industry, but NOT a complete beginner: they already know the
basics of solar and batteries and/or have some sales or phone experience, and
they pick things up very quickly. So the target is a real closer role that
accepts 0-1 years of SOLAR experience, not a pure no-experience setter job.
- "Solar experience preferred / not essential", "we teach the product",
  "sales or phone experience required" -> good fits.
- "Minimum 2+ years closing solar" -> score 5 or below, but still list it if
  remote and otherwise strong; a fast learner can sometimes talk their way in.
- Pure setter / qualifier roles -> only in a short "Fallback" list.
- Prefer roles that can start soon (immediate start, short onboarding).

## Remote rules (unless the user explicitly allows field work)
- Keep only roles done from home: phone / video consultations.
- Drop roles that need driving to homes, canvassing, in-home appointments, or
  regular office days, even when the listing says "Remote". Mention strong ones
  under "Watch out" so the user knows why they were dropped.
- "Hybrid" or "in-home OR virtual": keep only if the posting suggests remote is
  negotiable, and say what must be confirmed in the interview.
- Note any state/region the closer must live in.

## How to work
1. Search broadly with several phrasings ("solar closer", "solar and battery
   sales consultant", "solar telesales", "energy consultant phone sales",
   "work from home solar sales", "remote battery sales", "inside sales solar").
2. Open the actual posting (web_fetch) before you rank anything. Titles lie.
3. Keep only postings from roughly the last 45 days that you could actually open.
   Never invent a listing, company, pay figure, or URL. If a job board won't
   load, say so rather than guessing its contents.

{market}

## Scoring (1-10) - higher when the posting shows
- Warm / inbound / pre-qualified leads supplied (no cold calling).
- A base salary, hourly rate, or paid training on top of commission.
- Batteries in the product line.
- A real installer, retailer, or established brand behind the role.
- Clear commission numbers and clawback/cancellation terms.
Lower when: mislabeled role, fake remote, implausibly wide pay ranges, hidden
company identity, or a company name unrelated to energy.

## Hard red flags (list separately, never recommend)
- Asking the applicant to pay for training, licences, leads, or a "starter kit".
- MLM / recruit-your-own-downline structures.
- Requests for bank details, tax file / social security numbers, or ID before
  an interview or written offer.

## Output (Markdown only)
One-paragraph summary of the remote market you saw (be honest if it's thin).
Then the top matches, best first:
| Score | Role (linked to the posting) | Company | Truly remote? | Experience asked | Pay (base / commission) | Leads supplied? | Batteries? | Why it fits |
Then "Fallback" (remote setter roles), "Watch out" (attractive but mislabeled,
hybrid, or state-limited), and "Red flags".
Finish with 3-5 next steps: which to apply to first, and questions to ask in
the interview (lead source and volume, base vs commission, clawbacks on
cancelled jobs, how batteries are paid, whether the role is 100% remote in
writing).
"""

MARKETS = {
    "AU": """\
## Market: Australia (amounts in AUD)
- Search SEEK, Indeed AU, LinkedIn, Jora, and Glassdoor AU, plus the careers
  pages of solar and battery retailers.
- Work rights: the candidate is in Australia and works Australian hours. Skip
  overseas employers unless the posting explicitly hires Australian residents
  (as employees or ABN contractors); if you include one, flag time zone,
  currency, and who actually employs them.
- Employment type matters: a PAYG employee must get at least the award
  minimum plus super, so "commission only" is only legitimate for a genuine
  ABN contractor. Say which one each role is, and flag "employee" roles that
  appear to be commission-only.
- Home batteries are booming because of the federal battery rebate (Cheaper
  Home Batteries Program), so battery-heavy roles are a plus. Don't quote
  rebate amounts unless the posting does.
- Phone sales to households must follow telemarketing rules (calling hours,
  Do Not Call Register) and unsolicited-sales rules; a posting that brags about
  aggressive cold-calling volume or "no cooling-off" is a warning sign.
- Solar retailers that sign the New Energy Tech Consumer Code (NETCC) are a
  mild positive signal; mention it only if the posting or company site says so.
- Many "remote" listings are tied to one state (e.g. VIC, NSW, QLD). Say which.""",
    "US": """\
## Market: United States (amounts in USD)
- Search Indeed, ZipRecruiter, LinkedIn, and Glassdoor, plus installer and
  dealer career pages.
- Note W-2 vs 1099, and whether the closer must live in or be licensed for
  particular states.""",
}


def build_request(args: argparse.Namespace) -> str:
    country = "Australia" if args.country == "AU" else "the United States"
    where = f"I live in {args.location}, {country}" if args.location else f"I live in {country} and can work from anywhere in it"
    if args.allow_field:
        mode = "Remote roles first, but in-person or field roles near me are also fine."
    else:
        mode = "Remote only: I must be able to do the whole job from home."
    extra = f"\nAdditional preferences: {args.notes}" if args.notes else ""
    return (
        f"Today is {dt.date.today():%B %d, %Y}.\n"
        f"Find up to {args.max_results} solar closer gigs for me. {where}. {mode}\n"
        "I'm new to the solar industry, but I already know the basics of panels and "
        "batteries and I learn very quickly, so look for closer roles that take people "
        "who are new to solar rather than beginner setter jobs."
        f"{extra}"
    )


def run_agent(args: argparse.Namespace) -> str:
    client = anthropic.Anthropic()

    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": args.max_searches},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": args.max_searches * 2},
    ]
    location = {"type": "approximate", "country": args.country}
    if args.location:
        city, _, region = (part.strip() for part in args.location.partition(","))
        location["city"] = city
        if region:
            location["region"] = region
    tools[0]["user_location"] = location

    system = SYSTEM_PROMPT.replace("{market}", MARKETS[args.country])
    messages: list = [{"role": "user", "content": build_request(args)}]

    for _ in range(MAX_CONTINUATIONS + 1):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=system,
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
    parser = argparse.ArgumentParser(description="Find remote solar closer gigs for someone new to solar.")
    parser.add_argument("--country", default="AU", choices=sorted(MARKETS), help="Job market to search (default: AU)")
    parser.add_argument("--location", help='Where you live, e.g. "Brisbane, QLD" (some remote roles are limited to one state)')
    parser.add_argument("--allow-field", action="store_true", help="Also include in-person / field roles (default: remote only)")
    parser.add_argument("--notes", help='Extra preferences, e.g. "base salary required, batteries preferred"')
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
