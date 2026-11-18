# Prompt packs

Each pack is a ready-made set of shots for one Reel. The Studio makes a still for each shot
(Qwen image), animates it (Wan 2.2, Standard, about 5 seconds), and Reelcut puts the prompt
on top and the shot below.

| Pack | Reel | Posts |
|---|---|---|
| `wolves.json` | Prompt vs. the shot: the wolves short | Sat Dec 5 (Reel 9) |
| `villeneuve.json` | Shot Like: Villeneuve, but AI | Sat Dec 19 |

## Run one (Studio open, four green lights)

```bash
cd ~/reelcut-tool && git pull
python3 scripts/run_pack.py studio/packs/wolves.json --stills-only   # optional: check the looks first
python3 scripts/run_pack.py studio/packs/wolves.json                  # stills + clips, prints the Reelcut command
```

It runs the shots one after another and saves progress to `~/Movies/Reels/packs/`.
If a shot looks wrong, redo just that one: `--only 2`. When every shot is done it prints
the `reelcut.py prompt` command that builds the finished Reel in `~/Movies/Reels/`.

Everything stays on the Mac: the script only talks to the Studio at 127.0.0.1.
