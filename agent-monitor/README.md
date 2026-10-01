# Agent Monitor

See what your Claude Code agents are doing, live: which agents are running, what each one is doing right now, which tools and services they are talking to, and when one is waiting on you.


Three panels:

- **Agents**: every session (main agent) with its subagents nested underneath, each with a status (Working, Needs you, Idle, Done, Error) and its current action in plain words.
- **Who's talking to what**: main agents → subagents → tools and services (Files, Shell, Code search, Web, each MCP server). Green dashed lines are calls happening now, blue ones happened in the last minute, red ones failed.
- **Activity**: a plain-language feed ("Explore agent searched code for `calculateTax`", "shop-api is asking permission to run `git push`"). Click any agent to filter to it.

## Your accounts tab

Opened on claude.ai, the page also shows your Claude Code sessions and everything that changed in the last 3 days across your connected accounts: emails you sent, email in trash, calendar changes, Drive files, GitHub pull requests and code pushes, plus recently opened Notion pages. It reads through your claude.ai connectors with your own sign-in, asks once before connecting, and can only look: it has no tools that send, edit or delete.

## Approval before deleting or sending email

`.claude/settings.json` in this repo (and `server.py --install` for your own computer) adds Claude Code `ask` rules, so an agent must get your OK before it:

- sends, replies to or forwards email (Gmail tools, mail commands, Zapier write actions)
- deletes, trashes or removes anything through a connected service
- deletes files, branches or repos (`rm`, `git clean`, `git branch -D`, `git push --delete`, `gh repo delete`, and similar)

Ask rules prompt even in auto mode. They match the usual way an agent writes these commands; they are a safety net, not a security boundary (see the Claude Code permissions docs).

## Setup (one time, about a minute)

Needs Python 3.8+ and nothing else.

```bash
python3 server.py --install      # adds HTTP hooks to ~/.claude/settings.json (saves a .bak first)
python3 server.py                # start the monitor
```

Open http://127.0.0.1:4820, then start or restart Claude Code. Agents show up as soon as they do anything.

- Per-project instead of everywhere: `python3 server.py --install --project` (writes `.claude/settings.local.json` in the current folder).
- Different port: pass `--port 5000` to both commands.
- Remove it: `python3 server.py --uninstall`.

## How it works

Claude Code [hooks](https://code.claude.com/docs/en/hooks) of type `http` POST each event (prompt submitted, tool about to run, tool finished or failed, subagent started or stopped, permission requested, turn finished) to `server.py`. The server keeps the last 3,000 events in memory and streams them to the page. Nothing is written to disk and it only listens on `127.0.0.1`.

If the monitor isn't running, the hook request fails fast (2 s timeout) and Claude Code carries on as normal. The server always answers with an empty decision, so it never blocks or changes what agents do.

Opening `index.html` directly (not from the server) plays a built-in demo.
