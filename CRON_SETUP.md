# Run predictions every 30 minutes (cron)

Run these in **Terminal** (Applications → Utilities → Terminal, or Cmd+Space → “Terminal”).

## One-time setup

```bash
chmod +x "/Users/josephpang/repos/projects/Project 2/scripts/cron_run.sh"
crontab -e
```

When the editor opens, add this line (runs every 30 min):

```
*/30 * * * * "/Users/josephpang/repos/projects/Project 2/scripts/cron_run.sh"
```

- **nano:** Paste the line → Ctrl+O, Enter, Ctrl+X  
- **vim:** Press `i`, paste, Esc, then type `:wq` and Enter  

## Check it’s installed

```bash
crontab -l
```

## Where output goes

JSON is appended to:

```
Project 2/logs/nba_picks.jsonl
```

One line per run (each line is the full JSON for that run’s games).

## Stop running every 30 min

```bash
crontab -e
```

Delete the line with `cron_run.sh`, save and exit.
