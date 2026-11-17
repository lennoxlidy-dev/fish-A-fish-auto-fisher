# Fish A Fish – Auto Fisher

An auto fisher (macro) for the Roblox game
[Fish A Fish](https://www.roblox.com/games/98205335106967/Fish-A-Fish).

It works like a player would: it **looks at your screen** and **presses the mouse/keys**.
It does **not** inject scripts, use an executor, or read/modify the game's memory.

> ⚠️ **Heads-up:** Using macros/automation can break Roblox's or the game's rules, and AFK-farming
> can get an account warned or banned. Use it at your own risk, ideally in a private server,
> and don't leave it running unattended for days.

---

## Quick start (Windows)

1. **Install Python 3.10+** from <https://www.python.org/downloads/>.
   On the first installer screen, tick **"Add python.exe to PATH"**.
2. **Download this project** (green **Code** button → **Download ZIP**) and unzip it.
3. Open Roblox, join **Fish A Fish**, and put the window how you'll play (fullscreen is easiest).
4. Double-click **`setup.bat`**. It installs what it needs and asks you a few questions
   about how fishing works in the game. When it asks you to *capture* something,
   switch to Roblox, hover the mouse over the thing, and press **F8**.
5. Double-click **`run.bat`**, click on the Roblox window, and press **F6** to start.

| Key | What it does |
| --- | --- |
| **F6** | Start / pause |
| **F7** | Quit |
| **F8** | Capture (during setup / tools) |
| Mouse in the **top-left corner** of the screen | Emergency pause |

The macro also pauses by itself if Roblox isn't the active window, and lets go of every
key and mouse button whenever it pauses.

> Don't move or resize the Roblox window after setup: the macro remembers screen positions.
> If you change it, just run `setup.bat` again.

---

## How it works

Every round is: **cast → wait for a bite → reel → close popups → (sometimes) sell → repeat.**

Setup asks how each step works in Fish A Fish and saves your answers to `config.json`:

| Step | Options |
| --- | --- |
| **Cast** | click · hold the mouse (fixed time, or until the power bar is full) · press/hold a key |
| **Bite** | wait a fixed time · wait until something **appears** (`!`, "Click!", popup…) · wait until something **disappears** (bobber goes under) · optional click to hook |
| **Reel** | **spam** click/key · **hold** · **bar** (keep the fish inside your bar by holding/letting go) · **zone** (press when a moving marker is inside the target zone) · **target** (click things that pop up) · **wait** (it reels itself) |
| **After catch** | nothing · press a key · click a button |
| **Auto sell** | optional: run your own steps (keys, clicks, waits) every N catches |

"Watching the screen" means: inside a box you mark, look for a colour you picked. Setup
measures how many matching pixels there are when the thing is visible and when it's gone,
and picks a threshold between them.

**No setup?** Without a `config.json` it uses simple defaults: click to cast, wait 3 s,
spam-click for 8 s, repeat.

---

## Tools

```bash
python fisher.py check
```
Shows live what the macro sees (pixel counts, where it thinks the fish and bar are).
Press **F8** to save screenshots to `debug/` with the matching pixels painted pink/cyan.
Use this when something isn't being detected. (`check.bat` does the same.)

```bash
python fisher.py picker
```
Shows the mouse position and the colour under it, live. Handy for editing `config.json`
by hand.

---

## Tweaking `config.json`

You can edit it with Notepad. You only need the settings you want to change. Everything
else uses the defaults in [`autofisher/config.py`](autofisher/config.py).
[`config.example.json`](config.example.json) shows a full example (its positions are made up).

Most useful settings:

| Setting | Meaning |
| --- | --- |
| `reel.clicks_per_second` | speed for spam mode (1–40) |
| `reel.duration` | how long to reel when it isn't watching the screen |
| `reel.end_grace` | how long the reel screen must be gone before it counts as finished |
| `reel.bar.lookahead` | bar mode: bigger = lets go earlier (less overshoot). Try 0.1–0.25 |
| `reel.bar.deadzone` | bar mode: pixels of "close enough" |
| `*.tolerance` | how different a colour can be and still match (0–255, default 30) |
| `*.min_pixels` | how many matching pixels count as "it's there" |
| `bite.timeout` | recast if nothing bites in this many seconds |
| `after_catch.wait` | pause before the next cast |
| `humanize.timing_jitter` | random ±% on waits (0.1 = ±10%) |
| `start_paused` | `false` = start right away without pressing F6 |
| `require_roblox_focus` | `false` = don't pause when Roblox isn't the active window |

Actions (for `bite.on_bite`, `bite.on_timeout`, `after_catch.actions`, `auto_sell.actions`):

```json
[
  {"press": "e"},
  {"wait": 1.5},
  {"click": [1500, 700]},
  {"click": "default"},
  {"hold": "w", "duration": 2.0}
]
```

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Clicks / keys do nothing in Roblox | Make sure Roblox is the active window. Try `"wiggle_mouse": true` (default). If Roblox runs as administrator, run the macro as administrator too. |
| It never sees the bite / reel screen | Run `check.bat` while fishing. If the counts don't change, run setup again and pick a more unique colour, or raise `tolerance`. |
| Positions are off | Windows display scaling and moving the window both shift things. Keep Roblox in the same place and re-run setup. |
| Bar mode overshoots / wobbles | Raise `reel.bar.lookahead` (e.g. 0.2). If it reacts too late, lower it. |
| `python` is not recognised | Reinstall Python with **"Add python.exe to PATH"** ticked. |

**Mac:** it also runs on macOS (`python3 -m pip install -r requirements.txt`, then
`python3 fisher.py setup`). You'll need to allow your terminal under
*Accessibility*, *Input Monitoring* and *Screen Recording* in System Settings → Privacy & Security.
The automatic pause when Roblox isn't the active window only works on Windows.

---

## For developers

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

The fishing loop is tested against a simulated fishing game (`tests/fakes.py`) with a fake
clock, screen and input, so the logic can be checked without Roblox.

```
fisher.py              entry point (run / setup / picker / check)
autofisher/bot.py      the cast → bite → reel loop and the bar/zone controllers
autofisher/vision.py   colour matching and position finding (numpy)
autofisher/wizard.py   interactive setup
autofisher/config.py   defaults + validation of config.json
autofisher/inputs.py   mouse/keyboard (pydirectinput on Windows, pynput elsewhere)
autofisher/screen.py   screen capture (mss)
autofisher/tools.py    check + picker
```
