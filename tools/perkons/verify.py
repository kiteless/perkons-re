"""Behavioural checks shared by tests and tools/build.py, run through M7System (real
main() wiring block, real message handling, real audio callback)."""
from .emu import M7System

HOME = {'cFirstSlot': 0, 'cSecondSlot': 1, 'cThirdSlot': 2, 'cFourthSlot': 3}
DEFAULT_PARAMS = [1500, 2500, 1800, 3000]


def boot(img, sym, freeze_rand=True):
    e = M7System(img.segment('m7').data, sym, img.segment('m4').data, freeze_rand=freeze_rand).boot()
    e.send(3, 3, b'\x01')  # "samples ready": load factory samples (no SD in the emulator)
    e.pump()
    return e


def engine_map_of(e):
    """Which stock voice's engine each output of a running emulator runs (by RTTI class)."""
    return [HOME[e.class_of(e.slot(o))] for o in range(4)]


def engine_map(img, sym):
    """Which stock voice's engine each output runs after boot."""
    return engine_map_of(boot(img, sym))


def render_output(img, sym, out, algo, mode, n=6000, params=DEFAULT_PARAMS):
    """Set one output's knobs/switches, trigger only that output, render it."""
    e = boot(img, sym)
    voices = [{'params': [2048] * 4} for _ in range(4)]
    voices[out] = {'params': params, 'algo': algo, 'mode': mode}
    e.send_voice_state(voices)
    e.pump()
    am = [(0, 0)] * 4
    am[out] = (algo, mode)
    e.send_triggers([o == out for o in range(4)], am)
    return e.audio(n)[out]


def compare_to_stock(stock, patched, sym, algos=range(3), modes=range(3), n=6000):
    """For every output, check it renders exactly what the stock engine it runs renders
    at that engine's home output. Returns a list of (out, algo, mode, engine, ok)."""
    results = []
    emap = engine_map(patched, sym)
    for out in range(4):
        for algo in algos:
            for mode in modes:
                got = render_output(patched, sym, out, algo, mode, n)
                ref = render_output(stock, sym, emap[out], algo, mode, n)
                results.append((out, algo, mode, emap[out], got == ref))
    return results

