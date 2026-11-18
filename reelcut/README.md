# Reelcut

Turns finished footage into vertical Reels and Shorts in one command.
Every export is **1080×1920, 30 fps, H.264 + AAC**, with no platform watermark, so the same file goes to Instagram and YouTube Shorts.

Standalone: it doesn't touch the AI Studio app, its queue or its models. It only needs Python 3 and ffmpeg, reads the clips you point it at and writes mp4s. It never posts or uploads anything.

## Set up on the Mac Studio (once)

```bash
brew install ffmpeg                 # skip if `ffmpeg -version` already works
cd ~/WatsonFactorAIStudio           # your clone of this repo
git fetch origin reelcut && git checkout reelcut
python3 reelcut/test_reelcut.py     # should end with "8/8 passed"
```

Clips from the AI Studio (`Studio_Output/<project>/*.mp4`) work as inputs. They have no sound, so Reelcut adds silence or your `--music` track.

## This week's three Reels

**Reel 1, Thursday: Prompt vs. the shot (Farola Run)**

1. Export the three shots you want (balcony, street, whiskey pour) from Resolve as separate mp4s.
2. Open `reelcut/recipes/farola-prompt-vs-shot.json`, paste the real Gemini prompts, fix the clip paths, and optionally set `"music"` to a track you have the rights to.
3. Run:

```bash
python3 reelcut/reelcut.py prompt --recipe reelcut/recipes/farola-prompt-vs-shot.json --numbered --out ~/Movies/Reels/reel1-prompt-vs-shot.mp4
```

**Reel 2, Saturday: Setup vs. the shot (run-and-gun rig)**

```bash
python3 reelcut/reelcut.py stack \
  --top ~/Movies/BeautyInTheDark/final_shot.mp4 \
  --bottom ~/Movies/BeautyInTheDark/phone_bts.mp4 \
  --top-label "THE SHOT" --bottom-label "THE SETUP" \
  --hook "Same camera. No crew. Pitch black room." \
  --duration 12 \
  --out ~/Movies/Reels/reel2-setup-vs-shot.mp4
```

**Reel 3, Tuesday: Farola Run in three parts (Part 1 posts Tuesday, Part 2 Saturday, Part 3 the week after)**

Pick cut points that each end on a tense frame, then:

```bash
python3 reelcut/reelcut.py parts \
  --input ~/Movies/FarolaRun/farola_ep1.mp4 \
  --at "0:34,1:08" \
  --hooks "She poured his whiskey. He never checked the bottle.|He found the leak. It was sitting next to him.|" \
  --end-texts "Part 2 Saturday|Part 3 next week|Episode 2?" \
  --out-prefix ~/Movies/Reels/farola
```

That writes `farola_part1of3.mp4`, `farola_part2of3.mp4` and `farola_part3of3.mp4`. The default `--fit blur` keeps the whole 16:9 frame over a blurred fill; use `--fit crop` to fill the screen instead.

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

Shared options: `--hook`, `--hook-secs`, `--end-text`, `--end-secs`, `--music`, `--music-volume`, `--font`, `--dry-run` (prints the ffmpeg command, writes nothing). Run `python3 reelcut/reelcut.py <command> -h` for the rest.

## Notes

- Hooks sit in the top third, clear of Instagram's caption and button area at the bottom.
- Fonts: Arial Bold for captions and Menlo for the typed prompt, from macOS. Override with `--font` / `--mono-font`.
- Mark realistic AI footage as AI or altered content when you upload. That's a setting in each app; Reelcut doesn't add a label.
- Tested on synthetic clips on Linux with ffmpeg 6.1 (`test_reelcut.py`, 8/8). Not yet run on the Mac Studio or on real footage.
