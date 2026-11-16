# 🏈 Fantasy Football Companion for Yahoo

A self-hosted assistant for your Yahoo Fantasy Football team. It connects to your league,
does the weekly research for you, tells you how to set your lineup around NFL schedules,
spots trade and waiver opportunities, and sends alerts to your phone.

| | |
|---|---|
| **Dashboard** | Record, standings, this week's matchup, and the projected gain from fixing your lineup |
| **Lineup optimizer** | Best legal lineup from projections, injuries, byes and game locks. One click applies it to Yahoo |
| **Schedule-aware** | Kickoff timeline. Your latest-kickoff player goes in FLEX so you can still pivot. Players already in a game stay locked |
| **Player research** | Projection, last 3 vs season average, trend, floor/ceiling, consistency, matchup grade (defense vs position) and a plain-English outlook |
| **Graphs** | Weekly points vs opponent vs projection, points by position, points left on your bench, each starter's weekly form |
| **Trades** | 1-for-1 trade ideas that improve your starting lineup without hurting theirs, plus buy-low and sell-high candidates and your positional strength vs the league |
| **Waivers** | Available players ranked by how much they'd upgrade *your* lineup, boosted by how many leagues are adding them |
| **Bye planner** | Who you lose each of the next 6 weeks and any lineup slot you won't be able to fill |
| **Notifications** | Injury status changes, starters on bye or ruled out, lineup fixes worth points, waiver targets, trade ideas and watchlist changes. Sent via phone push (ntfy), Discord, Slack or email |

Data: your league comes from the **Yahoo Fantasy API**. Player news, injuries, projections, stats and
trending adds come from **Sleeper's public API**, and the NFL schedule and kickoff times from **ESPN**.
Neither of those needs a key.

## Quick start (demo mode, no accounts needed)

```bash
pip install -r requirements.txt
python -m companion serve
```

Open http://localhost:8000. With no Yahoo keys set, the app runs on a made-up demo league so you can
look around.

## App styles

Pick a look from the **Style** menu in the header. Your choice is remembered in that browser.
You can also link to one directly with `?style=<name>`.

| Style | Feel |
|---|---|
| `midnight` (default) | Navy glass with blue-violet gradients |
| `turf` | Stadium green, yard-line background, condensed sports type |
| `primetime` | TV broadcast: navy with red/gold, bold uppercase Oswald headings, square edges |
| `scoreboard` | Retro amber LED, monospace numbers with glow |
| `aurora` | Frosted glass cards over vivid cyan/violet/pink light |
| `stealth` | Pure black and white minimal |

Every style is dark, and the charts use the same colorblind-checked series colors in each one.

## Connect your Yahoo league

1. Go to https://developer.yahoo.com/apps/create/ and create an app:
   - **Application type:** Web Application
   - **Redirect URI(s):** `https://localhost:8000/auth/callback`
   - **API permissions:** Fantasy Sports → **Read/Write** (write lets the app set your lineup)
2. Copy `.env.example` to `.env` and fill in `YAHOO_CLIENT_ID` and `YAHOO_CLIENT_SECRET`.
   Leave `YAHOO_REDIRECT_URI=oob`.
3. Run `python -m companion serve` and open http://localhost:8000. Click **Sign in with Yahoo**,
   approve, and paste the code Yahoo shows into the box.
   (Or run `python -m companion login` in the terminal.)
   - If Yahoo rejects `oob`, set `YAHOO_REDIRECT_URI=https://localhost:8000/auth/callback`. After you
     approve, your browser will fail to load that page. That's expected: paste the whole URL from the
     address bar into the code box.
4. If you're in more than one league, choose it in the **Alerts** tab. You can also pin one with
   `YAHOO_LEAGUE_KEY` in `.env`.

Tokens are stored locally in `data/companion.db` and refresh automatically.

## Notifications

Set any of these in `.env`, then use **Alerts → Send test notification**:

- **Phone push (easiest):** install the free [ntfy](https://ntfy.sh) app, subscribe to a hard-to-guess
  topic name, and set `NTFY_TOPIC` to the same name.
- **Discord / Slack:** set `DISCORD_WEBHOOK_URL` / `SLACK_WEBHOOK_URL` to an incoming-webhook URL.
- **Email:** set the `SMTP_*`, `EMAIL_FROM` and `EMAIL_TO` values. For Gmail, use an app password.

While the server runs, it checks your team every `MONITOR_INTERVAL_MINUTES` (default 60). Each alert is
sent only once, and new alerts are bundled into a single digest per check.

| Alert | When |
|---|---|
| Injury change | A player on your roster changes status (e.g. healthy → questionable → out) |
| Lineup problem | A starter is on bye or ruled out, or a better lineup is worth ≥ `LINEUP_GAIN_ALERT` points |
| Inactives check | A questionable starter kicks off within 3 hours |
| Waiver target | An available player is trending (≥ `WAIVER_TREND_MIN` adds) or would upgrade your lineup |
| Trade idea / buy-low / sell-high | New ideas each week |
| Watchlist | A watched player's status or fantasy owner changes |
| Bye crunch | You won't be able to fill a slot in an upcoming week |

### Running it all the time

The monitor only runs while the server is up. To keep it running:

- Leave `python -m companion serve` running on an always-on computer, or deploy it to any small VPS or
  container host (`python -m companion serve --host 0.0.0.0`). Put it behind HTTPS and a password if
  you expose it to the internet: anyone who can reach it can change your lineup.
- Or skip the server and run checks from cron:
  `0 * * * * cd /path/to/fantasyfootballtracker && python -m companion check`

## Command line

```bash
python -m companion serve [--host 0.0.0.0 --port 8000]   # dashboard + background monitor
python -m companion login                                # connect Yahoo in the terminal
python -m companion lineup [--week 11]                   # print the recommended lineup
python -m companion check                                # one monitoring pass (cron-friendly)
python -m companion test-notify                          # test your notification setup
```

## How the recommendations work

- **Projections** come from Sleeper, in your league's PPR / half-PPR / standard format (detected from
  the league's reception scoring). Each projection is discounted for injury designation:
  questionable ×0.85, doubtful ×0.3, out/IR ×0. Players on bye count as 0.
- **Lineup:** an exact assignment solver (Hungarian algorithm) fills every starting slot, including
  flex and superflex, to maximize projected points. Players whose games have started stay where they
  are. Among equal choices, the latest-kickoff player goes in FLEX.
- **Matchup grade:** each defense's average fantasy points allowed per game to each position this
  season, ranked 1–32 (A = among the most generous).
- **Player value** (used for trades, waivers and byes): 45% this week's projection, 35% last-3-game
  average and 20% season average, discounted for injuries.
- **Trade ideas:** every 1-for-1 swap with every team, kept only when it raises your optimal lineup by
  at least 1 point per week and doesn't lower theirs. That makes them offers the other manager might
  actually accept.

Weekly player points use Sleeper's scoring for your PPR format, so they can differ slightly from Yahoo
if your league has custom scoring. Team totals and matchups come straight from Yahoo.

## Development

```bash
pip install -r requirements.txt
python -m pytest
```

Code layout: `companion/sources/` (Yahoo, Sleeper/ESPN, demo), `lineup.py`, `research.py`,
`trades.py`, `monitor.py`, `notifier.py`, `service.py` (ties it together), `app.py` (web API) and
`static/` (dashboard).
