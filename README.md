# 🎧 AI DJ

An AI DJ that mixes a playlist on its own. Hand it a playlist link or a stack of songs:
it listens to every track, keeps the ones that groove together, puts them in the
smoothest order, and blends each transition on the downbeat — basslines swap cleanly,
never stacked.

## What it does

- **Build a set** — paste an Audius, Jamendo or Internet Archive playlist or album link,
  or upload your own files. Mixing runs as a background job (it survives page refreshes)
  and produces an MP3, a tracklist crediting every artist, and a cut sheet showing exactly
  where each transition lands.
- **DJ booth** — a live two-deck view of the mix: spinning turntables, per-stem faders that
  follow the mix engine's real curves, a crossfader, a bass-swap light and a spectrum
  visualizer.
- **Structure-aware transitions** — mixes out of each track's outro into the next track's
  intro, starting on a downbeat, with the tempo matched.
- **Auto-ordering** — sequences tracks for the smallest tempo, key and energy jumps.
- **Discover** — search free catalogs that serve full-length audio and preview tracks
  before adding them.

## How a transition is made

1. **Analyze** — [All-In-One](https://github.com/mir-aidj/all-in-one) finds the sections
   (intro, verse, chorus, break, outro…), beats, downbeats and tempo. The key comes from
   Essentia when installed, otherwise librosa. Demucs splits each track into drums, bass,
   vocals and everything else, reusing All-In-One's own separation pass.
2. **Choose** — pairs are scored on tempo gap, Camelot-wheel distance and energy. A track
   with no tempo neighbour within 6% sits out rather than being stretched until it sounds
   wrong.
3. **Order** — greedy nearest-neighbour plus local search over every possible pairing.
4. **Plan** — each blend starts on a downbeat in the outgoing track's outro (or its last
   32 bars when no outro is detected) and runs 16–64 bars. It never runs past the end of
   that track's music, and never overlaps the previous blend.
5. **Render** — the outgoing track is time-stretched to the incoming tempo. Drums and other
   parts crossfade at equal power, while bass and vocals hand over at the midpoint, so two
   basslines never clash. Audio streams to disk, then a VBR MP3 and the tracklist are
   written.

## Setup

Requires Python 3.10 or 3.11, on macOS or Linux.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/streamlit run src/ai_dj/web.py
```

The first analysis downloads the Demucs and All-In-One models. On a CPU, expect roughly
three minutes of analysis per track; results are cached, so each track is only analyzed
once.

Jamendo search and Jamendo links need a free
[client ID](https://devportal.jamendo.com/): paste it in the sidebar, or
`export JAMENDO_CLIENT_ID=...`. The Internet Archive and Audius need no key.

## Command line

With the virtualenv active:

```bash
aidj demo                       # fetch 10 Creative Commons tracks, then analyze, order and mix them
aidj info path/to/track.mp3     # sections, tempo and key for a track
aidj mix a.mp3 b.mp3 c.mp3 -o data/output/mix.wav
aidj search house -n 10         # search Jamendo (needs a client ID)
```

## Music sources and licensing

A DJ mix needs the **whole** track, so only catalogs that serve full-length audio are
supported: Audius, Jamendo and the Internet Archive. Spotify, Apple Music, YouTube and
SoundCloud can't work — they don't give other apps the audio.

- Downloads follow each platform's rules. On Audius, for example, artists decide whether a
  track can be downloaded, and the app never works around that.
- "Remixable licences only" keeps Creative Commons licences that allow derivative works —
  a mix is one.
- Every mix comes with a tracklist crediting artists and licences. A mix that contains
  "All rights reserved" tracks is for personal listening only.

Downloaded audio, analysis caches and rendered mixes live under `data/` and are not
committed to the repository.
