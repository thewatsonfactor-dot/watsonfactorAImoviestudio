# Reelcut

Turns finished footage into vertical Reels and Shorts in one command.
Every export is **1080×1920, 30 fps, H.264 + AAC**, with no platform watermark, so the same file goes to Instagram and YouTube Shorts.

Standalone: it doesn't touch the AI Studio app, its queue or its models. It only needs Python 3 and ffmpeg, reads the clips you point it at and writes mp4s. It never posts or uploads anything.

## Set up on the Mac Studio (once)

```bash
brew install ffmpeg                 # skip if `ffmpeg -version` already works
cd ~/WatsonFactorAIStudio           # your clone of this repo
git fetch origin reelcut
git checkout origin/reelcut -- reelcut   # copies just the reelcut/ folder; your current branch and work stay as they are
python3 reelcut/test_reelcut.py     # should end with "15/15 passed"
```

## Find your footage on the external drive

Your drive mounts at `/Volumes/Watson dev`. The name has a space, so keep it in quotes in every command.

```bash
ls /Volumes                                         # should list "Watson dev"; if not, plug it in
ls "/Volumes/Watson dev"                            # the top-level folders on the drive
python3 reelcut/reelcut.py scan "/Volumes/Watson dev"            # every video on the drive
python3 reelcut/reelcut.py scan "/Volumes/Watson dev" --name twisted  # only names containing "twisted"
```

`scan` lists each clip's length, resolution, codec, size and full path, so you can copy the path straight into a command. Lines marked `ok` work as they are. Lines marked `EXPORT` are camera RAW (Blackmagic RAW `.braw`, RED, ARRIRAW, ProRes RAW), which ffmpeg can't read: export those from DaVinci Resolve first (Deliver page, H.264 or ProRes 422) and use the export. Reelcut skips the hidden `._` files macOS leaves on external drives.

**Outputs stay off the drive.** Reelcut reads from the drive but won't write a Reel onto the same drive unless you add `--allow-source-drive`. Every example below writes to `~/Movies/Reels/` on the Mac.

Clips from the AI Studio (`Studio_Output/<project>/*.mp4`) work as inputs. They have no sound, so Reelcut adds silence or your `--music` track.

## This week's Reels

Reel 1 is **Twisted Fate in three parts**: Part 1 Thursday, Part 2 next Tuesday, Part 3 the Saturday after. All three come from one command.

1. Find the Twisted Fate edit on the drive (your footage may be under a `Movies` folder there):

```bash
ls "/Volumes/Watson dev/Movies"
python3 reelcut/reelcut.py scan "/Volumes/Watson dev" --name twisted
```

2. The cut points below are for the 1:26 edited version on YouTube: 0:30 lands on her close-up after "Don't do that", 0:58 on her face after "I need you to trust me". If your file on the drive is a different cut, check those two moments and adjust `--at`.
3. Run, with the path `scan` printed:

```bash
python3 reelcut/reelcut.py parts \
  --input "/Volumes/Watson dev/Movies/<folder>/twisted_fate.mov" \
  --at "0:30,0:58" \
  --hooks "She came home late. Again.|What's in the envelope?|Are we still in this together?" \
  --end-texts "Part 2 Tuesday|Part 3 Saturday|Volume 2?" \
  --out-prefix ~/Movies/Reels/twisted_fate
```

That writes `twisted_fate_part1of3.mp4`, `twisted_fate_part2of3.mp4` and `twisted_fate_part3of3.mp4` to `~/Movies/Reels/`. The default `--fit blur` keeps the whole 16:9 frame over a blurred fill; use `--fit crop` to fill the screen instead.

**Reel 2, Saturday: Setup vs. the shot (run-and-gun rig)**

```bash
python3 reelcut/reelcut.py stack \
  --top "/Volumes/Watson dev/Movies/<folder>/final_shot.mov" \
  --bottom "/Volumes/Watson dev/Movies/<folder>/phone_bts.mp4" \
  --top-label "THE SHOT" --bottom-label "THE SETUP" \
  --hook "Same camera. No crew. Pitch black room." \
  --duration 12 \
  --out ~/Movies/Reels/reel2-setup-vs-shot.mp4
```

Swap `<folder>` and the file names for the real ones from `scan`.

## Week 3: Prompt vs. the shot (wolves short)

Open `reelcut/recipes/prompt-vs-shot-template.json`, paste the real prompts, point each `"clip"` at the matching AI Studio output (or the path `scan` printed), and optionally set `"music"` to a track you have the rights to. Then:

```bash
python3 reelcut/reelcut.py prompt --recipe reelcut/recipes/prompt-vs-shot-template.json --numbered --out ~/Movies/Reels/reel9-prompt-vs-shot.mp4
```

## Week 2: LOG vs. graded

Export the same shot twice from Resolve (once with the grade bypassed, once graded), same in and out points:

```bash
python3 reelcut/reelcut.py wipe --before log.mp4 --after graded.mp4 \
  --hook "What the Pocket 4K actually records vs. what you see" \
  --out ~/Movies/Reels/reel6-log-vs-graded.mp4
```

## All commands

| Command | Does |
|---|---|
| `stack` | Two clips stacked top and bottom, labels, white seam |
| `prompt` | Prompt types out on top, shot plays below; several pairs joined |
| `parts` | One video cut into N parts (or at `--at` times), "PART 1 / 3" labels, hooks and end cards |
| `wipe` | Before/after wipe with a moving divider |
| `vertical` | One clip reframed to 9:16 (`--fit crop` or `--fit blur`) |
| `scan` | Lists the videos in a folder or drive, flags RAW files to export first |

Shared options: `--hook`, `--hook-secs`, `--end-text`, `--end-secs`, `--music`, `--music-volume`, `--font`, `--allow-source-drive`, `--dry-run` (prints the ffmpeg command, writes nothing). Run `python3 reelcut/reelcut.py <command> -h` for the rest.

## Notes

- Hooks sit in the top third, clear of Instagram's caption and button area at the bottom.
- Fonts: Arial Bold for captions and Menlo for the typed prompt, from macOS. Override with `--font` / `--mono-font`.
- Mark realistic AI footage as AI or altered content when you upload. That's a setting in each app; Reelcut doesn't add a label.
- Tested on synthetic clips on Linux with ffmpeg 6.1, including a fake external drive (`test_reelcut.py`, 15/15). Not yet run on the Mac Studio or on real footage.
