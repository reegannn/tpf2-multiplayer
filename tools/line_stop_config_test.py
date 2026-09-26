"""A line stop's cargo filter (Line.StopConfig) through the real Lua, on Lua 5.2.

The line editor lets each stop load and unload only some cargo types and cap a
cargo's share of the capacity: stop.stopConfig = {load, unload, maxLoad}, one
entry per cargo type. Replays built every stop with an empty config, so a filter
set in the editor was reset on every instance, the originator's included. This
loads the real stopconfig.lua, lines.lua and inject.lua with stub CM/api and
checks:

  - lineSnapshot writes the config as the stop's "@load:unload:maxLoad" suffix,
    in front of the waypoint suffix, and nothing for a default stop;
  - a decoded LUPDATE from the slice (" sc=<stop>:<cfg>,...") puts the same
    suffix on the right stop, before its waypoints (" wp=");
  - execLine's replay sets the config on the api.type.Line.Stop it builds, the
    flags as the INTEGERS 1 and 0. The stub's vectors refuse anything else the way
    the game does ("stack index 3, expected number, received boolean: not an
    integer": booleans dropped every filter in the first game test, 2026-09-26);
  - the waypoint and numeric fields still read the same with a config present;
  - a filter change is a re-set of the same stop to mergeLineEdit, and the
    stops signature (LCREATE matching) ignores the suffix;
  - a malformed sc= tail is refused, not shipped.

    python tools/line_stop_config_test.py
"""
import os
import sys

import lupa.lua52 as lupa

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MP = os.path.join(REPO, "mod", "mp_lockstep_1", "res", "scripts", "mp")

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({extra})" if extra else ""))
    if not cond:
        fails.append(name)


def runtime():
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = L.globals()
    g.package.path = (os.path.join(REPO, "mod/mp_lockstep_1/res/scripts/?.lua").replace("\\", "/")
                      + ";" + g.package.path)
    g.LINES_SRC = open(os.path.join(MP, "lines.lua"), encoding="utf-8").read()
    return L.execute(r'''
local logs, sent = {}, {}
local function sink()
  return setmetatable({}, { __index = function() return sink() end, __call = function() return nil end })
end
-- station groups 5000 (station 5001) at 100,200 and 6000 (station 6001) at 400,500.
-- Line 42: stop 1 loads cargo 1 and 3 only, unloads cargo 2, cargo 3 capped at
-- half the train; stop 2 is a default stop.
local pos = { [5000] = {100, 200}, [5001] = {101.5, 202.5},
              [6000] = {400, 500}, [6001] = {401.5, 502.5} }
local groupStations = { [5000] = {5001}, [6000] = {6001} }
local lineStops = {
  { stationGroup = 5000, station = 0, terminal = 0, loadMode = 0,
    minWaitingTime = 0, maxWaitingTime = 180, waypoints = {}, alternativeTerminals = {},
    stopConfig = { load = { 1, 0, 1 }, unload = { 0, 1, 0 },
                   maxLoad = { 1, 1, 0.5 } } },
  { stationGroup = 6000, station = 0, terminal = 1, loadMode = 0,
    minWaitingTime = 0, maxWaitingTime = 180, waypoints = {}, alternativeTerminals = {},
    stopConfig = { load = {}, unload = {}, maxLoad = {} } },
}
-- a StopConfig vector as the game binds it: the flags take integers only, maxLoad
-- any number; read back by index and #, never ipairs (a userdata container)
local function engineVec(flags)
  local store = {}
  return setmetatable({}, {
    __index = function(_, k) return store[k] end,
    __newindex = function(_, k, v)
      if type(v) ~= "number" or (flags and v % 1 ~= 0) then
        error("stack index 3, expected number, received " .. type(v) .. (flags and ": not an integer" or ""))
      end
      if type(k) ~= "number" or k < 1 or k > #store + 1 then error("index out of range: " .. tostring(k)) end
      store[k] = v
    end,
    __len = function() return #store end,
  })
end
local CT = { LINE = 1, STATION_GROUP = 4, PLAYER_OWNED = 5, COLOR = 6, MODEL_INSTANCE_LIST = 7, SIGNAL_LIST = 8 }
api = setmetatable({}, { __index = function() return sink() end })
api.type = setmetatable({
  ComponentType = CT,
  Line = { new = function() return { stops = {} } end,
           Stop = { new = function() return { waypoints = {}, alternativeTerminals = {},
                                              stopConfig = { load = engineVec(true), unload = engineVec(true),
                                                             maxLoad = engineVec(false) } } end } },
  StationTerminal = { new = function() return {} end },
  SignalId = { new = function() return {} end },
}, { __index = function() return sink() end })
api.engine = setmetatable({
  entityExists = function(id) return pos[id] ~= nil end,
  getComponent = function(id, k)
    if k == CT.LINE and id == 42 then return { stops = lineStops, waitingTime = 180 } end
    if k == CT.STATION_GROUP then return { stations = groupStations[id] } end
    -- waypoint 7000: a signal model at 1,2,3
    if id == 7000 and k == CT.MODEL_INSTANCE_LIST then
      return { fatInstances = { { modelId = 9, transf = { [13] = 1, [14] = 2, [15] = 3 } } } }
    end
    if id == 7000 and k == CT.SIGNAL_LIST then return { signals = { {} } } end
    return nil
  end,
  util = { getPlayer = function() return 2002 end },
  system = { lineSystem = { getLines = function() return { 42 } end } },
}, { __index = function() return sink() end })
api.res = { modelRep = { getName = function() return "wp.mdl" end } }
api.cmd = {
  make = { updateLine = function(lid, line) return { what = "updateLine", lid = lid, line = line } end },
  sendCommand = function(cmd, cb) sent[#sent + 1] = cmd; if cb then cb(nil, true) end end,
}
game = setmetatable({ interface = {
  getName = function() return "Coal" end,
  getEntity = function(id) if pos[id] then return { position = pos[id] } end return {} end,
  getEntities = function(_, opts)
    if opts and opts.type == "STATION_GROUP" then return { 5000, 6000 } end
    return {}
  end,
} }, { __index = function() return sink() end })

local K = setmetatable({ INSTANCE = "b", PEER = "a", BASE = "",
                         STRICT_OPS = { LCREATE = true, LUPDATE = true, LDELETE = true } },
  { __index = function() return nil end })
local CM = { peerSeen = true, ticks = 0, seqNo = 0, queue = {}, peers = {} }
function CM.gameTime() return 100 end
function CM.stepOf(t) return math.floor((t or 0) / 0.2 + 0.5) end
function CM.scheduleLocal() end
function CM.escName(s) return (tostring(s or ""):gsub(" ", "%%20")) end
function CM.unescName(s)
  return (tostring(s or ""):gsub("%%(%x%x)", function(h) return string.char(tonumber(h, 16)) end))
end
function CM.cmMayUse() return true end
function CM.cmMayModify() return true end
local log = function(s) logs[#logs + 1] = s end
assert(load(LINES_SRC, "@lines.lua"))()(CM, K, log)
function CM.lineKeyFor(id) if id == 42 then return "b:1" end end
function CM.lineIdFor(key) if key == "b:1" then return 42 end end
-- waypoints: resolved by the stub below, so a record with both suffixes replays
function CM.findStopNear() return 7000 end

local H = { CM = CM }
function H.snapStops() local s = CM.lineSnapshot(42); return s and s.stops end
function H.replay(stops)
  sent = {}
  CM.execLine({ op = "LUPDATE", origin = "a", seq = 5, at = 100, key = "b:1",
                name = "Coal", color = "0.1,0.2,0.3", wait = 180,
                stops = stops, alts = "", armed = 1 })
end
function H.nsent() return #sent end
local function sentStop(i) local c = sent[1]; return c and c.line and c.line.stops[i] end
function H.sentVec(i, field)
  local s = sentStop(i); if not s or not s.stopConfig then return nil end
  local out = {}
  local vec = s.stopConfig[field]
  for k = 1, #vec do out[k] = type(vec[k]) .. ":" .. tostring(vec[k]) end
  return table.concat(out, ",")
end
function H.sentWaypoint(i) local s = sentStop(i); return s and s.waypoints[1] and s.waypoints[1].entity end
function H.sentField(i, field) local s = sentStop(i); return s and s[field] end
function H.capture(line, stops)
  local t = {}
  for rec in stops:gmatch("[^;]+") do t[#t + 1] = rec end
  local ok, err = pcall(CM.lineCaptureStopConfig, line, t)
  if not ok then return "ERR " .. tostring(err) end
  return table.concat(t, ";")
end
function H.merge(b, c, p)
  local s, a, adds, dels, sets = CM.mergeLineEdit(b, "", c, "", p, "")
  return s, adds, dels, sets
end
function H.sigEqual(a, b) return CM.stopsSigEqual(a, b) end
function H.logs() return table.concat(logs, "\n") end
return H
''')


def main():
    H = runtime()

    # 1. The snapshot carries the filter as the stop's suffix; the default stop none.
    stops = H.snapStops()
    recs = (stops or "").split(";")
    check("snapshot: two stops", len(recs) == 2, str(stops))
    check("snapshot: stop 1 ends with its cargo filter", recs[0].endswith("@101:010:1/1/0.5"), recs[0])
    check("snapshot: the default stop carries no suffix", "@" not in recs[1], recs[1])

    # 2. Replayed, the config reaches the Stop the command is built from.
    H.replay(stops)
    check("replay: one updateLine sent", H.nsent() == 1)
    check("replay: stop 1 load flags, as integers", H.sentVec(1, "load") == "number:1,number:0,number:1",
          str(H.sentVec(1, "load")))
    check("replay: stop 1 unload flags, as integers", H.sentVec(1, "unload") == "number:0,number:1,number:0",
          str(H.sentVec(1, "unload")))
    check("replay: stop 1 maxLoad", H.sentVec(1, "maxLoad") == "number:1,number:1,number:0.5",
          str(H.sentVec(1, "maxLoad")))
    check("replay: stop 2 keeps the default (empty) config", H.sentVec(2, "load") == "" and H.sentVec(2, "maxLoad") == "",
          f"{H.sentVec(2, 'load')!r} {H.sentVec(2, 'maxLoad')!r}")
    check("replay: the numeric fields still read (terminal, maxWaitingTime)",
          H.sentField(2, "terminal") == 1 and H.sentField(1, "maxWaitingTime") == 180,
          f"{H.sentField(2, 'terminal')} {H.sentField(1, 'maxWaitingTime')}")
    check("replay: nothing refused", "not applied" not in H.logs() and "REJECT" not in H.logs(), H.logs()[-400:])

    # 2b. The filter from the first game test, exactly as the slice read it (17 cargo
    # types; load and unload set, maxLoad left empty by the game).
    real_load, real_unload = "11111111101111000", "11111111101101000"
    real = f"100.00,200.00,0,4,0,0,180,101.5,202.5@{real_load}:{real_unload}:;" + recs[1]
    H.replay(real)
    want = lambda bits: ",".join("number:" + b for b in bits)
    check("replay, the game's own filter: all 17 load flags", H.sentVec(1, "load") == want(real_load), str(H.sentVec(1, "load")))
    check("replay, the game's own filter: all 17 unload flags", H.sentVec(1, "unload") == want(real_unload), str(H.sentVec(1, "unload")))
    check("replay, the game's own filter: maxLoad stays empty", H.sentVec(1, "maxLoad") == "", str(H.sentVec(1, "maxLoad")))

    # 3. The slice's decoded LUPDATE: sc= goes onto the right stop, before the waypoints.
    base = "100.00,200.00,0,0,0,0,180,101.5,202.5;400.00,500.00,0,1,0,0,180,401.5,502.5"
    got = H.capture("LUPDATE 42 180 2 5000 0 0 0 0 180 0 6000 0 1 0 0 180 0 sc=2:01:10:0.25/1 wp=2:7000:0 asg=0", base)
    check("capture: the filter lands on stop 2 only", not got.startswith("ERR") and got.split(";")[1].endswith("@01:10:0.25/1")
          and "@" not in got.split(";")[0], got)
    got2 = H.capture("LUPDATE 42 180 2 x sc=1:01:1x:1", base)
    check("capture: a malformed tail is refused", got2.startswith("ERR") and "Invalid" in got2, got2)
    got3 = H.capture("LUPDATE 42 180 2 no tail", base)
    check("capture: no sc= tail, the records are untouched", got3 == base, str(got3))

    # 4. Filter and waypoint suffixes together still replay.
    both = recs[0] + "~1.000:2.000:3.000:wp.mdl:0" + ";" + recs[1]
    H.replay(both)
    check("replay: filter plus waypoints -- the filter still arrives",
          H.sentVec(1, "maxLoad") == "number:1,number:1,number:0.5", str(H.sentVec(1, "maxLoad")))
    check("replay: filter plus waypoints -- the waypoint still arrives", H.sentWaypoint(1) == 7000, str(H.sentWaypoint(1)))

    # 5. Merging and matching.
    plain = recs[0].split("@")[0]
    click = recs[0].replace("@101:010:1/1/0.5", "@111:000:1/1/1")
    s, adds, dels, sets = H.merge(recs[0] + ";" + recs[1], click + ";" + recs[1], recs[0] + ";" + recs[1])
    check("merge: a changed filter is a re-set of the same stop", (adds, dels, sets) == (0, 0, 1) and s.split(";")[0] == click,
          f"+{adds} -{dels} ~{sets} {s}")
    check("signature: the suffix is not part of the stops signature",
          H.sigEqual(recs[0] + ";" + recs[1], plain + ";" + recs[1]) is True)
    check("signature: different stops still differ",
          H.sigEqual(recs[0] + ";" + recs[1], recs[1] + ";" + recs[0]) is False)

    print()
    if fails:
        print(f"{len(fails)} FAILED: " + ", ".join(fails))
        return 1
    print("PASS: a stop's cargo filter is read back, captured off the slice, shipped with its stop, "
          "and set on the replayed line")
    return 0


if __name__ == "__main__":
    sys.exit(main())
