# Ideas for Quote Vault

Written on 2026-11-18. Nothing here is built yet. Ordered by how much it would help, most useful first within each group.

## Protect and finish what exists

- **Backups.** The library is plain files in `library/` with no history. Keep the folder in iCloud Drive or under version control, so one bad edit or a lost Mac does not lose the cards. iCloud would also make the cards readable on the phone when the Mac is off.
- **Faster online check.** The check waits for the slowest source, up to 14 seconds. Show each source's answer as it arrives, so most checks feel instant.
- **Microphone and phone, still untested.** Nobody has yet confirmed that macOS asks for microphone permission in the Mac app, or run the phone setup (`scripts/setup-phone-https.sh`).
- **Tag suggestions.** The local model reuses existing tags too readily, even when they fit poorly.
- **Turkish correction misses.** Words with two valid spellings (`oldu`/`öldü`, `olur`/`ölür`) are not resolved, and `herşey` is not split into `her şey`.
- **Cross-language check.** It missed the Sapiens test line ("Tarihin en büyük sahtekârlığı tarım devrimidir"). Not re-tested since Google Books was added.

## Features likely to be used most

- **Review mode for facts.** A slideshow shows cards at random. A review mode would hide part of the fact, ask "knew it" or "didn't", and bring missed facts back sooner (spaced repetition). Suggested as the first feature to build.
- **Photo capture.** Photograph a page with the phone; the Mac reads the highlighted passage, so nothing is typed. Can run locally and free with the text recognition built into macOS.
- **Meaning-based search and related cards.** The model that compares sentences by meaning (`bge-m3`) is already installed for the cross-language check. Use it to find cards about a theme even when the word is absent, and to show similar cards from other books on the back of each card.

## Nice to have

- **Import.** Kindle highlights (`My Clippings.txt`) and Apple Books highlights, so past reading comes in at once. Photos of the old physical cards could come in through photo capture.
- **Card of the day.** One card shown when the app opens.
- **Share a card as an image.** For sending a quote to someone.
- **Per-book summary.** What a book meant to you, written by the local model from your own highlights.
- **Fact checking.** Look a fact up on Wikipedia. Rated lowest: a wrong "confirmed" is worse than no check.

## Suggested next session

Backups first, then review mode for facts.
