"""Button and knob combinations: what each mod uses, what the stock firmware and the platform
use, and the checks the Mod Matrix and the build make with them.

An option lists its controls in mod.json (optional for now: an option without the list
says nothing about its controls):

    "controls": [
      {"combo": "KIT + SYNC (HOLD)",     buttons, knobs or switches, the first held, joined by +;
                                         a gesture in brackets: (HOLD), (TAP), (HOLD 0.5 S)
       "page": "ANY",                    where it works: ANY (the default), MAIN, PATTERN, KIT,
                                         BANK, MOD, CONFIG, MIDI CHANNELS, ENGINES, or a
                                         mod's own page
       "does": "OPENS THE SIDECHAIN PAGE",
       "adds": false}                    true: stock's own action still happens, the mod only
                                         adds to it (a copy that also copies the mod's data)
    ]

Two controls are the same combination when they press the same buttons (in any order,
gestures aside) on overlapping pages (ANY overlaps every page). Then:
  * two options' controls: a clash, they can't be built together (check_clashes);
  * an option's control and one of the platform's: a clash too;
  * an option's control and a stock one: the option changes what that stock combination
    does (stock_changes). The Mod Matrix asks the user first; it builds.
A control that only adds to stock's action ("adds": true) is neither. A combination that
contains a stock one but presses more (TRIGGER + LFO RATE beside stock's TRIGGER) is a
different combination.
"""
import re

BUTTONS = ('PLAY', 'REC', 'RESET', 'SHIFT', 'CLEAR', 'LAST', 'SHUFFLE', 'PATTERN', 'KIT', 'SYNC',
           'MOD', 'RATCHET', 'ODDS1', 'ODDS2', 'PROB', 'TRIGGER', 'STEP')
KNOBS = ('KNOB', 'TUNE', 'DECAY', 'PARAM1', 'PARAM2', 'CUTOFF', 'DRIVE', 'FX SEND', 'LEVEL',
         'ALGO', 'MODE', 'FILTER SWITCH', 'TEMPO', 'LFO RATE', 'LFO WAVE', 'MOD LVL',
         'FX TIME', 'FX FEEDBACK', 'FX LFO RATE', 'FX MOD DEPTH', 'FX SWITCH')
CONFIG_KEY = re.compile(r'^ROW [1-4] STEP ([1-9]|1[0-6])$')     # a key on the CONFIG page
ANY = 'ANY'

# The stock firmware's combinations (firmware 1.3.0, from the manual, in our words). Single
# buttons and single knobs aren't listed: a mod using one with something else is a new
# combination. The FX switch is: it's a stock control a mod can take over.
STOCK = [
    {'combo': 'SHIFT + TEMPO', 'page': 'MAIN', 'does': 'SHOWS THE TEMPO ON THE STEPS'},
    {'combo': 'SHIFT + STEP', 'page': 'MAIN', 'does': 'DIVIDE, MULTIPLY, GROOVE AND PLAY MODE PER TRACK; TEMPO FINE-TUNING'},
    {'combo': 'SHIFT + RESET', 'page': 'MAIN', 'does': 'TEMPO CONTROLS ON THE TRIGGER KEYS (OR TRACK ROTATION)'},
    {'combo': 'SHIFT + RESET + TRIGGER', 'page': 'MAIN', 'does': 'HARD RESET, TAP TEMPO, NUDGE'},
    {'combo': 'SHIFT + LAST', 'page': 'MAIN', 'does': 'MASTER PATTERN LENGTH'},
    {'combo': 'SHIFT + SHUFFLE', 'page': 'MAIN', 'does': 'FILL MODE'},
    {'combo': 'SHIFT + SHUFFLE + TRIGGER', 'page': 'MAIN', 'does': 'PLAYS A FILL ON THAT TRACK'},
    {'combo': 'SHIFT + KNOB', 'page': 'MAIN', 'does': 'TURNS THAT KNOB ON ALL FOUR VOICES'},
    {'combo': 'SHIFT + MOD', 'page': ANY, 'does': 'OPENS THE CONFIG PAGE'},
    {'combo': 'SHIFT + TRIGGER', 'page': 'MAIN', 'does': 'MUTES THE TRACK'},
    {'combo': 'CLEAR + TRIGGER', 'page': 'MAIN', 'does': 'CLEARS THE TRACK AND ITS AUTOMATION'},
    {'combo': 'SHIFT + CLEAR + TRIGGER', 'page': 'MAIN', 'does': 'CLEARS THE TRACK\'S AUTOMATION ONLY'},
    {'combo': 'CLEAR + STEP', 'page': 'MAIN', 'does': 'CLEARS THE STEP'},
    {'combo': 'CLEAR + KIT', 'page': ANY, 'does': 'DROPS THE KIT\'S LOCKS: THE KNOBS AS THEY ARE'},
    {'combo': 'REC + TRIGGER', 'page': 'MAIN', 'does': 'TAP PROGRAMMING'},
    {'combo': 'STEP + KNOB', 'page': 'MAIN', 'does': 'PARAMETER LOCK ON THE STEP'},
    {'combo': 'STEP + REC', 'page': 'MAIN', 'does': 'COPIES THE STEP'},
    {'combo': 'STEP + SHIFT', 'page': 'MAIN', 'does': 'PASTES INTO THE STEP'},
    {'combo': 'STEP + RATCHET', 'page': 'MAIN', 'does': 'SHOWS THE STEP\'S SETTINGS'},
    {'combo': 'STEP + ODDS1', 'page': 'MAIN', 'does': 'SHOWS THE STEP\'S SETTINGS'},
    {'combo': 'STEP + ODDS2', 'page': 'MAIN', 'does': 'SHOWS THE STEP\'S SETTINGS'},
    {'combo': 'STEP + PROB', 'page': 'MAIN', 'does': 'SHOWS THE STEP\'S SETTINGS'},
    {'combo': 'STEP + RATCHET + TRIGGER', 'page': 'MAIN', 'does': 'SETS THE STEP\'S RATCHET'},
    {'combo': 'STEP + ODDS1 + TRIGGER', 'page': 'MAIN', 'does': 'SETS THE STEP\'S ODDS'},
    {'combo': 'STEP + ODDS2 + TRIGGER', 'page': 'MAIN', 'does': 'SETS THE STEP\'S ODDS'},
    {'combo': 'STEP + PROB + TRIGGER', 'page': 'MAIN', 'does': 'SETS THE STEP\'S PROBABILITY'},
    {'combo': 'PATTERN + REC', 'page': ANY, 'does': 'SAVES THE PLAYING PATTERN'},
    {'combo': 'PATTERN + KIT', 'page': ANY, 'does': 'OPENS THE BANK PAGE'},
    {'combo': 'REC + STEP', 'page': 'PATTERN', 'does': 'SAVES THE PATTERN IN THAT SLOT'},
    {'combo': 'SHIFT + STEP', 'page': 'PATTERN', 'does': 'SWITCHES TO THAT PATTERN AT ONCE'},
    {'combo': 'CLEAR + STEP', 'page': 'PATTERN', 'does': 'CLEARS THAT PATTERN'},
    {'combo': 'REC + STEP', 'page': 'KIT', 'does': 'SAVES THE KIT IN THAT SLOT'},
    {'combo': 'CLEAR + STEP', 'page': 'KIT', 'does': 'CLEARS THAT KIT'},
    {'combo': 'STEP + CLEAR', 'page': 'MOD', 'does': 'CLEARS THE STEP\'S MODULATION'},
    {'combo': 'CLEAR + TRIGGER', 'page': 'MOD', 'does': 'CLEARS THE VOICE\'S MODULATION'},
    {'combo': 'FX SWITCH', 'page': ANY, 'does': 'DELAY: SHORT OR LONG'},
]

# The platform's (voice-map, in every build): no option can use these
PLATFORM = [
    {'combo': 'KIT + MOD', 'page': ANY, 'does': 'OPENS THE ENGINE PAGE'},
    {'combo': 'STEP (HOLD 0.5 S)', 'page': 'ENGINES', 'does': 'OPENS THAT ENGINE\'S SETTINGS PAGE, IF IT HAS ONE'},
]


class ControlsError(Exception):
    pass


def parts(combo):
    """'KIT + SYNC (HOLD)' -> ['KIT', 'SYNC']: its buttons, knobs and switches, gestures aside."""
    return [re.sub(r'\s*\(.*?\)\s*', ' ', p).strip().upper() for p in combo.split('+')]


def key(c):
    """What makes two controls the same combination: the set of parts (and the page apart)."""
    return frozenset(parts(c['combo']))


def page(c):
    return str(c.get('page') or ANY).strip().upper()


def overlap(a, b):
    pa, pb = page(a), page(b)
    return pa == ANY or pb == ANY or pa == pb


def same(a, b):
    return key(a) == key(b) and overlap(a, b)


def validate(controls, where=''):
    """A mod.json controls list, checked: a list of {combo, page?, does, adds?} with known
    parts. Returns it (None stays None: not given)."""
    if controls is None:
        return None
    if not isinstance(controls, list):
        raise ControlsError(f'{where}: controls must be a list')
    for c in controls:
        if not isinstance(c, dict) or not isinstance(c.get('combo'), str) or not isinstance(c.get('does'), str):
            raise ControlsError(f'{where}: each control needs a combo and what it does')
        if set(c) - {'combo', 'page', 'does', 'adds'}:
            raise ControlsError(f'{where}: {c["combo"]}: unknown fields {sorted(set(c) - {"combo", "page", "does", "adds"})}')
        for p in parts(c['combo']):
            if p not in BUTTONS and p not in KNOBS and not CONFIG_KEY.match(p):
                raise ControlsError(f'{where}: {c["combo"]}: {p!r} is not a Perkons control '
                                    f'(buttons: {", ".join(BUTTONS)}; knobs and switches: {", ".join(KNOBS)}; '
                                    f'config keys: ROW r STEP s)')
        if CONFIG_KEY.match(parts(c['combo'])[0]) and page(c) != 'CONFIG':
            raise ControlsError(f'{where}: {c["combo"]}: a config key works on the CONFIG page')
    return controls


def counted(controls):
    """The controls that can clash or change stock: those that don't only add to stock's."""
    return [c for c in controls or [] if not c.get('adds')]


def check_clashes(options):
    """Error text for the first two options (or an option and the platform) using the same
    combination; None if there's none."""
    seen = [('the platform', c) for c in PLATFORM]
    for o in options:
        for c in counted(o.get('controls')):
            for who, d in seen:
                if same(c, d):
                    return f'{o["title"]} and {who} both use {c["combo"]} ({page(c)})'
        seen += [(o['title'], c) for c in counted(o.get('controls'))]
    return None


def stock_changes(option):
    """[(the option's control, the stock control)] whose stock combination it changes."""
    return [(c, s) for c in counted(option.get('controls')) for s in STOCK if same(c, s)]


# -- docs/controls.md: its tables, from the lists above -----------------------------------

DOC = 'docs/controls.md'
BEGIN, END = '<!-- tables: python3 -m perkons.controls (from tools/) -->', '<!-- end of tables -->'


def tables():
    def rows(cs):
        return '\n'.join(f'| {c["combo"]} | {page(c).title() if page(c) != ANY else "any"} | '
                         f'{c["does"][0] + c["does"][1:].lower()} |' for c in cs)
    head = '| combination | page | does |\n|---|---|---|\n'
    return (f'### Stock (firmware 1.3.0)\n\n{head}{rows(STOCK)}\n\n'
            f'### The platform (every build)\n\n{head}{rows(PLATFORM)}\n')


def write_doc(root):
    import os
    path = os.path.join(root, DOC)
    text = open(path).read()
    a, b = text.index(BEGIN) + len(BEGIN), text.index(END)
    new = text[:a] + '\n\n' + tables() + '\n' + text[b:]
    if new != text:
        with open(path, 'w') as f:
            f.write(new)
    return new != text


if __name__ == '__main__':
    import os
    write_doc(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
