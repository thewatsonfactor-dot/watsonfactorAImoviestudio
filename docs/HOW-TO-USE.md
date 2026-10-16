# How to use Watson Factor AI Studio

1. **Plug in the WFStudio SSD, then click "Watson Factor AI Studio" in the Dock.** The engine starts (about 20 seconds) and the dashboard opens in your browser.
2. **Check the four lights at the top right.** All green means you can render. Hover any light that isn't green to see what to fix.
3. **On Create, drop a keyframe** (or paste one with ⌘V). Write a short motion prompt about what moves and how the camera moves. Keep it under the token limit; Wan ignores anything past about 512 tokens.
4. **Pick a project, a length and a quality, then press Generate.** Use Draft for motion tests and Standard for keepers. Final (720p) is experimental on 36 GB. Watch progress live on Renders.
5. **Find finished clips in Library.** Hover a clip to play it. Use Re-roll for the same shot with a new seed, or Remix to tweak it in Create. Files are on the SSD in `Studio_Output/<project>/`, each with a `.json` file that records how it was made.

To shut everything down, click **Stop AI Studio** in Applications. To free up memory without shutting down, go to Settings and choose **Restart engine**.
