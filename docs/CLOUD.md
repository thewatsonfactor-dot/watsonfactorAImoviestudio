# Cloud shots

Your Studio frame, a top closed video model, every take logged.

The local Wan renders are for blocking and drafts. A hero shot goes to **Seedance 2.5** (ByteDance) or **Kling 3.0** (Kuaishou) at 1080p, starting from a frame you made in the Studio. You pay the provider per second of finished video, with your own account.

## 1. Sign up and get a key (one provider is enough)

| Provider | Sign up | Key | Notes |
|---|---|---|---|
| **Replicate** | replicate.com, sign in with GitHub | Account settings → API tokens (starts `r8_`) | Cheaper for Seedance. Add a card or prepaid credit under Billing first. |
| **fal.ai** | fal.ai, sign in with GitHub or Google | Dashboard → Keys (an id, a colon, a secret) | Prepaid credit. fal has no free key check, so the first take is the test; a wrong key is refused before anything runs. |

Set a monthly spend limit in the provider's billing page before your first take.

Paste the key in **Settings → Cloud keys** and press **Save**. It's written to `studio/config/keys.local.json` on this Mac (owner-only, never committed). The Studio shows only its last four characters after that. To remove it, press the bin icon.

## 2. What a take costs (estimates, Nov 22 2026)

| Model | Through | 720p, 5 s | 1080p, 5 s | 1080p, 10 s |
|---|---|---|---|---|
| Kling 3.0 | either | $0.45 | $0.60 | $1.20 |
| Seedance 2.5 | Replicate | $1.20 | $2.85 | $5.70 |
| Seedance 2.5 | fal.ai | $2.40 | $5.85 | $11.70 |

Sound multiplies the price by about 1.5. The Studio shows the estimate before every send and asks you to confirm it. Your provider's bill is the final word; check it after your first few takes, and update the prices in `studio/config/cloud.json` if they've moved.

## 3. Make a shot

1. **First frame.** On **Cloud shots**, press **From the Library** and pick a render: scrub to the frame you want, or use its opening frame (usually the cleanest). Or open any render in the Library and press **Cloud shot from this**. A still from the Image screen works too, and so does an uploaded image. A small frame (like 832×480) is fine; the model renders at the resolution you choose.
2. **Prompt.** Open the LENS panel, pick **Seedance prompt** or the shot stage, fill it, press **Fill the prompt**. Describe what moves and how the camera moves; the frame already shows what things look like. The project's look locks are added after your words. "What the model reads" shows the exact text.
3. **Model.** Pick Seedance 2.5 or Kling 3.0, the provider, the length and 1080p. Leave sound off unless you need it.
4. **Send.** Check the dollar amount in the dialog, then press **Send**. A take takes a few minutes. You can leave the screen; it keeps going, and picks up again if the Studio restarts.

## 4. The take library

Each take shows its video, model, provider, length, resolution, estimated cost and the full prompt. Star the keepers. The reload arrow puts a take's frame, prompt and settings back in the form so you can change one thing and send again. Files are in `Studio_Output/<project>/cloud/`, each with a `.json` that records the prompt, model, provider, cost and the frame it started from. Today's and this month's totals are under the Send button.

## Suggested first test

Kling 3.0, 5 seconds, 1080p, no sound, starting from the opening frame of a render you like: about **$0.60**. If it comes back, try the same frame and prompt on Seedance 2.5 (about $2.85 on Replicate) and compare.

## If something goes wrong

- **The take card shows the provider's error.** The Studio sends exactly the field names in `studio/config/cloud.json`. These were taken from the providers' docs and haven't been tried with a real key yet, so the first take may name a field to fix. Change it in the JSON (no code change), restart the Studio, send again. A refused take isn't charged.
- **"Add your key in Settings first."** No key is saved for that provider.
- **"The price changed to about $X."** The screen was showing an old estimate. Check the new number and send again.
- **A take sits in the queue.** Busy providers can queue for several minutes. The Studio gives up after 45 minutes; press the square to stop it sooner.

## Safety

- The key is only sent to `queue.fal.run` or `api.replicate.com`, over https. Downloads of the finished video carry no key.
- Keys never appear in logs, error messages, sidecar files, the API or the repository.
- Nothing is sent without your confirmation of the price.
- Only send frames of real people with their written consent; the providers' terms apply to what you upload.
