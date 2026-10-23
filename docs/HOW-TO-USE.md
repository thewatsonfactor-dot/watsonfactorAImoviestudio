# How to use Watson Factor AI Studio

1. **Plug in the WFStudio SSD, then click "Watson Factor AI Studio" in the Dock.** The engine starts (about 20 seconds) and the dashboard opens in your browser. If your SSD is a disk image (an `ssd_image` path in Settings), plug in the drive that holds it; the Studio mounts the image for you.
2. **Check the four lights at the top right.** All green means you can render. Hover any light that isn't green to see what to fix.
3. **Need a keyframe? Make one on Image.** Describe the shot like a film still. To put specific characters or places in it, drop up to three photos into Picture 1–3 and name them in the prompt ("the man in Picture 1 faces the woman in Picture 2"). Press **Make image**; it runs on this Mac with no content filter. When you like one, press **Animate** to send it to Create. (First time only: download the five image models on the Models screen, about 20 GB.) Only use real people's faces with their written consent.
4. **On Create, drop a keyframe** (or paste one with ⌘V). Write a short motion prompt about what moves and how the camera moves. Keep it under the token limit; Wan ignores anything past about 512 tokens.
5. **Pick a project, a length and a quality, then press Generate.** Use Draft for motion tests and Standard for keepers. Final (720p) is experimental on 36 GB. Watch progress live on Renders.
6. **Find finished clips and images in Library.** Hover a clip to play it. Use Re-roll for the same shot with a new seed, or Remix to tweak it. Images also have **Animate** and **Use as reference**. Files are on the SSD in `Studio_Output/<project>/`, each with a `.json` file that records how it was made.

To shut everything down, click **Stop AI Studio** in Applications. If the Studio mounted the disk image, it unmounts it too; if something is still using it, eject it from Finder. To free up memory without shutting down, go to Settings and choose **Restart engine**.
