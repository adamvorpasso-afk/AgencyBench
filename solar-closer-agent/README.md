# Solar Closer Gig Finder

An agent that searches the web for **remote** residential solar (and solar + battery) **closer** gigs, reads each posting, and ranks them for an **experienced solar closer** who wants remote, commission-based work (default), or with `--experience new` for someone new to solar who learns fast. **Australia** is the default market (SEEK, Indeed AU, LinkedIn, Jora); the US is supported with `--country US`. In experienced mode it skips setter and entry-level jobs and judges commission-only deals on lead volume, commission rate, clawbacks and payment timing.

For Australia it also checks whether a role is PAYG with super or an ABN contract, flags "remote" roles tied to one state, and gives extra points to battery-heavy roles, since demand is up with the federal battery rebate.

It doesn't take listings at face value. It opens each posting and checks for:
- **Mislabeled roles**: "Closer" in the title, but the actual job is knocking doors to set appointments.
- **Fake remote**: "Remote" in the location, but the duties are field canvassing.
- **Hype pay**: ranges like "$60k–$290k" or "average $2,500/week" with nothing to back them up.
- **Hard red flags**: paying for your own training or leads, MLM-style recruiting, or asking for your SSN or bank details before an interview.

It gives more points to paid training, a base pay or draw, appointments the company sets for you, batteries in the product line, and clear commission and clawback terms.

## Run

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...      # or: ant auth login
python solar_closer_agent.py                                     # Australia, remote only (default)
python solar_closer_agent.py --location "Brisbane, QLD"          # some remote roles are state-restricted
python solar_closer_agent.py --notes "base salary required, batteries preferred"
python solar_closer_agent.py --country US --location "Tampa, FL"
python solar_closer_agent.py --allow-field --location "Brisbane, QLD"   # also include in-person roles
```

Your report prints to the terminal and is also saved as `solar_gigs_<date>.md`.

Options: `--experience` (`experienced` default, or `new`), `--country` (`AU` default, or `US`), `--allow-field`, `--max-results`, `--max-searches` (caps web-search cost), `--effort` (`high` by default), `--out`.

Each run uses Claude Opus 5.5 with web search and web fetch. Expect a few minutes per run and roughly a dollar or less at the default settings. Server-side refusal fallback is turned on (`fallbacks: "default"`).
