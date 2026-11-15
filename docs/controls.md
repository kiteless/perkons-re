# Controls: the button and knob combinations mods use

Mods add gestures to the Pērkons's panel: KIT + SYNC to switch something on, a step held
with SHUFFLE to open a page. Two mods using the same combination would fight over it, and
a mod can quietly change what a stock combination does. So each mod lists the
combinations it uses, and the Mod Matrix checks them:

* **Two mods with the same combination can't be built together.** Ticking the second one
  asks first: OK takes the first one out and puts the second in, CANCEL keeps the first.
  The build refuses them too.
* **A mod that changes what a stock combination does** asks before it's ticked: the
  dialog shows what stock did and what the mod does instead. OK puts it in, CANCEL leaves
  it out.
* Every mod has a **[CONTROLS]** link beside its README: the combinations it uses.

A combination that only *contains* a stock one isn't a change: PER TRACK LFO uses a
trigger key held while turning an LFO knob, which stock gives no meaning, so the trigger
keys still work as they always did.

## Listing a mod's controls

In the option's entry in `mod.json` (for now optional; it will be required):

```json
"controls": [
  {"combo": "KIT + SYNC", "does": "TURNS THE SIDECHAIN ON OR OFF"},
  {"combo": "KIT + SYNC (HOLD 0.5 S)", "does": "OPENS THE SIDECHAIN PAGE"},
  {"combo": "STEP + SHUFFLE", "page": "MAIN", "does": "OPENS THE SAMPLE PAGE"},
  {"combo": "STEP + REC", "page": "MAIN", "does": "ALSO COPIES THE STEP'S SAMPLE", "adds": true},
  {"combo": "ROW 3 STEP 15", "page": "CONFIG", "does": "SWITCHES THE FX TO THE REVERB"}
]
```

* **combo**: the controls pressed or turned, the one held first first, joined by `+`. A
  gesture goes in brackets: `(HOLD)`, `(TAP)`, `(HOLD 0.5 S)`. Use these names:
  * buttons: PLAY, REC, RESET, SHIFT, CLEAR, LAST, SHUFFLE, PATTERN, KIT, SYNC, MOD,
    RATCHET, ODDS1, ODDS2, PROB, TRIGGER (a voice's trigger key), STEP (a step key)
  * knobs and switches: KNOB (any voice knob), TUNE, DECAY, PARAM1, PARAM2, CUTOFF, DRIVE,
    FX SEND, LEVEL, ALGO, MODE, FILTER SWITCH, TEMPO, LFO RATE, LFO WAVE, MOD LVL, FX TIME,
    FX FEEDBACK, FX LFO RATE, FX MOD DEPTH, FX SWITCH
  * config page keys: `ROW r STEP s`, with `"page": "CONFIG"`
* **page**: where it works: ANY (the default), MAIN, PATTERN, KIT, BANK, MOD, CONFIG,
  MIDI CHANNELS, ENGINES, or your mod's own page (its name).
* **does**: what it does, in a few words.
* **adds**: `true` when stock's own action still happens and the mod only adds to it
  (STEP SAMPLER's copy also copies the step's sample). These never clash and never count
  as a change.

Two combinations are the same when they use the same controls (in any order, gestures
aside) on the same page, or either works on ANY page. A mod with nothing to list gives an
empty list: `"controls": []`. Run `make manifest` afterwards: the Mod Matrix reads the
controls from the repo's manifest.

## Taken

These are the stock firmware's and the platform's. A mod can't use the platform's; using
a stock one is allowed, and the Mod Matrix tells the user before they tick it. Each mod's
own are under its [CONTROLS] link in the Mod Matrix.

<!-- tables: python3 -m perkons.controls (from tools/) -->

### Stock (firmware 1.3.0)

| combination | page | does |
|---|---|---|
| SHIFT + TEMPO | Main | Shows the tempo on the steps |
| SHIFT + STEP | Main | Divide, multiply, groove and play mode per track; tempo fine-tuning |
| SHIFT + RESET | Main | Tempo controls on the trigger keys (or track rotation) |
| SHIFT + RESET + TRIGGER | Main | Hard reset, tap tempo, nudge |
| SHIFT + LAST | Main | Master pattern length |
| SHIFT + SHUFFLE | Main | Fill mode |
| SHIFT + SHUFFLE + TRIGGER | Main | Plays a fill on that track |
| SHIFT + KNOB | Main | Turns that knob on all four voices |
| SHIFT + MOD | any | Opens the config page |
| SHIFT + TRIGGER | Main | Mutes the track |
| CLEAR + TRIGGER | Main | Clears the track and its automation |
| SHIFT + CLEAR + TRIGGER | Main | Clears the track's automation only |
| CLEAR + STEP | Main | Clears the step |
| CLEAR + KIT | any | Drops the kit's locks: the knobs as they are |
| REC + TRIGGER | Main | Tap programming |
| STEP + KNOB | Main | Parameter lock on the step |
| STEP + REC | Main | Copies the step |
| STEP + SHIFT | Main | Pastes into the step |
| STEP + RATCHET | Main | Shows the step's settings |
| STEP + ODDS1 | Main | Shows the step's settings |
| STEP + ODDS2 | Main | Shows the step's settings |
| STEP + PROB | Main | Shows the step's settings |
| STEP + RATCHET + TRIGGER | Main | Sets the step's ratchet |
| STEP + ODDS1 + TRIGGER | Main | Sets the step's odds |
| STEP + ODDS2 + TRIGGER | Main | Sets the step's odds |
| STEP + PROB + TRIGGER | Main | Sets the step's probability |
| PATTERN + REC | any | Saves the playing pattern |
| PATTERN + KIT | any | Opens the bank page |
| REC + STEP | Pattern | Saves the pattern in that slot |
| SHIFT + STEP | Pattern | Switches to that pattern at once |
| CLEAR + STEP | Pattern | Clears that pattern |
| REC + STEP | Kit | Saves the kit in that slot |
| CLEAR + STEP | Kit | Clears that kit |
| STEP + CLEAR | Mod | Clears the step's modulation |
| CLEAR + TRIGGER | Mod | Clears the voice's modulation |
| FX SWITCH | any | Delay: short or long |

### The platform (every build)

| combination | page | does |
|---|---|---|
| KIT + MOD | any | Opens the engine page |
| STEP (HOLD 0.5 S) | Engines | Opens that engine's settings page, if it has one |

<!-- end of tables -->
