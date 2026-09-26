"""Several ticks in a stop's cargo dialog, through the real inject.lua and lines.lua, on Lua 5.2.

Every tick in the line editor's cargo dialog is its own UpdateLine, built by the editor from
the line as the ENGINE holds it. Under lockstep an edit lands only at its stamp, and not at
all while the session is paused, so the next tick arrives built without the one before it.
The merge used to take the click's whole stop record, and every tick but the last was undone
(2026-09-26, in a game: "only gears" came back as every cargo). This drives the capture path
(decoded LUPDATE with the slice's sc= tail -> merge -> scheduled stops) with the harness of
line_rapid_edit_test.py and checks what finally lands:

  - three quick unticks (or ticks while paused) all land, on a stop whose filter the engine
    holds empty (a default stop) and on one it holds filled;
  - a tick built by an editor that did not refresh after the previous tick landed keeps both;
  - ticking a box back on still works, and the same tick twice is harmless;
  - two quick moves of one cargo's max-load slider: the last one wins;
  - a filter tick and a wait-mode change, or a filter tick and an added station, both land;
  - mergeStopConfig on its own: untouched entries keep the pending value, an emptied vector
    stays emptied.

    python tools/line_stop_config_clicks_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import line_rapid_edit_test as rapid  # noqa: E402  (its runtime loads the real inject.lua and lines.lua)

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({extra})" if extra else ""))
    if not cond:
        fails.append(name)


ALL = "11111:11111:1/1/1/1/1"   # five cargo types, everything on: what the editor fills a default stop with


def cfg(load, unload="11111", mx="1/1/1/1/1"):
    return f"{load}:{unload}:{mx}"


def load_bits(entity, stop=0):
    rec = entity.split(";")[stop]
    head = rec.split("~")[0]
    return head.split("@")[1].split(":")[0] if "@" in head else "(no filter)"


class Game:
    """One player's game: the inject file, the mod, and the engine's line."""

    def __init__(self, start_cfg, stations=(107158,)):
        path = os.path.join(tempfile.mkdtemp(), "lockstep_inject_b.txt")
        open(path, "wb").close()
        self.path = path
        self.H = rapid.runtime(path)
        # land a first update so the engine holds the starting filter
        self.click(start_cfg, stations=stations)
        self.land_all()

    def click(self, c, stations=(107158,), lm=0, cfg_stop=1):
        parts = ["LUPDATE", str(rapid.LID), "180", str(len(stations))]
        for sg in stations:
            parts += [str(sg), "0", "0", str(lm), "0", "180", "0"]
        line = " ".join(parts) + (f" sc={cfg_stop}:{c}" if c else "")
        with open(self.path, "ab") as f:
            f.write(("ARMED 1\n" + line + "\n").encode())
        self.H.poll()

    def land_one(self):
        return self.H.applyNext()

    def land_all(self):
        while self.H.applyNext():
            pass
        self.H.confirm()

    def entity(self):
        return self.H.entity()


def main():
    # 1. Three quick unticks (or while paused): nothing lands between them.
    for label, start in (("default stop (the engine holds no filter)", ""),
                         ("stop whose filter the engine holds filled", ALL)):
        g = Game(start)
        g.click(cfg("01111"))   # untick cargo 1
        g.click(cfg("10111"))   # untick cargo 2 -- built from the engine: cargo 1 still on
        g.click(cfg("11011"))   # untick cargo 3
        g.land_all()
        check(f"3 quick unticks, {label}: all three land", load_bits(g.entity()) == "00011", g.entity())

    # 2. "Only gears": untick 4 of 5 while paused, then the session runs.
    g = Game("")
    for k in range(5):
        if k == 2:
            continue   # gears
        bits = ["1"] * 5
        bits[k] = "0"
        g.click(cfg("".join(bits)))
    g.land_all()
    check("only gears (4 unticks while paused): only gears loads", load_bits(g.entity()) == "00100", g.entity())

    # 3. The editor did not refresh after tick 1 landed: tick 2 is built from the list before it.
    g = Game(ALL)
    g.click(cfg("01111"))
    g.land_one()                        # tick 1 is on the entity now
    g.click(cfg("10111"))               # built from the editor's stale all-on view
    g.land_all()
    check("stale editor after a landed tick: both land", load_bits(g.entity()) == "00111", g.entity())

    # 4. Ticking a box back on, and the same tick twice.
    g = Game(ALL)
    g.click(cfg("01111"))
    g.land_all()
    g.click(cfg("11111"))               # tick cargo 1 back on, built from the entity
    g.land_all()
    check("ticking a box back on works", load_bits(g.entity()) == "11111", g.entity())
    g.click(cfg("11101"))
    g.click(cfg("11101"))               # the same tick again before the first landed
    g.land_all()
    check("the same tick twice is harmless", load_bits(g.entity()) == "11101", g.entity())

    # 5. Two quick moves of cargo 2's max-load slider: the last one wins.
    g = Game(ALL)
    g.click(cfg("11111", mx="1/0.75/1/1/1"))
    g.click(cfg("11111", mx="1/0.5/1/1/1"))
    g.land_all()
    rec = g.entity().split("~")[0]
    check("two quick slider moves: the last wins", rec.endswith("@11111:11111:1/0.5/1/1/1"), rec)

    # 6. A filter tick, then a wait-mode change before it lands: both land.
    g = Game(ALL)
    g.click(cfg("01111"))
    g.click(ALL, lm=1)                  # full load, built from the engine: its filter is still all-on
    g.land_all()
    head = g.entity().split("@")[0].split(",")
    check("filter tick + wait-mode change: the filter lands", load_bits(g.entity()) == "01111", g.entity())
    check("filter tick + wait-mode change: the wait mode lands", len(head) >= 5 and head[4] == "1", g.entity())

    # 7. A filter tick, then a station added before it lands: both land.
    g = Game(ALL)
    g.click(cfg("01111"))
    g.click(ALL, stations=(107158, 107161))
    g.land_all()
    stops = g.entity().split(";")
    check("filter tick + added station: two stops", len(stops) == 2, g.entity())
    check("filter tick + added station: the filter lands", load_bits(g.entity()) == "01111", g.entity())

    # 8. mergeStopConfig on its own.
    H = rapid.runtime(os.path.join(tempfile.mkdtemp(), "x.txt"))
    m = H.CM.mergeStopConfig
    check("merge: untouched entries keep the pending value",
          m(cfg("11111"), cfg("11110"), cfg("01111")) == cfg("01110"))
    check("merge: a click that changed nothing keeps the pending filter",
          m(cfg("11111"), cfg("11111"), cfg("01111")) == cfg("01111"))
    check("merge: from a default stop (no filter), the fill counts as the base",
          m("", cfg("10111"), cfg("01111")) == cfg("00111"))
    check("merge: an emptied vector stays emptied", m(cfg("01111"), "::", cfg("01110")) == "")

    print()
    if fails:
        print(f"{len(fails)} FAILED: " + ", ".join(fails))
        return 1
    print("PASS: quick cargo-filter ticks all land, whatever the order they arrive in")
    return 0


if __name__ == "__main__":
    sys.exit(main())
