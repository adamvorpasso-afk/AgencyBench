# Solar Closer Gig Finder

An agent that searches the web for **remote, entry-level** residential solar (and solar + battery) **closer** gigs, reads each posting, and ranks them for someone new to the industry. It also lists remote **setter** roles as stepping stones, since that is how most newcomers get promoted to closer.

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
python solar_closer_agent.py                                   # remote + entry level (default)
python solar_closer_agent.py --location "Tampa, FL"            # some remote roles are state-restricted
python solar_closer_agent.py --notes "base pay or paid training only"
python solar_closer_agent.py --allow-field --location "Tampa, FL"   # also include in-person roles
```

Your report prints to the terminal and is also saved as `solar_gigs_<date>.md`.

Options: `--allow-field`, `--max-results`, `--max-searches` (caps web-search cost), `--effort` (`high` by default), `--out`.

Each run uses Claude Opus 5.5 with web search and web fetch. Expect a few minutes per run and roughly a dollar or less at the default settings. Server-side refusal fallback is turned on (`fallbacks: "default"`).
