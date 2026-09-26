-- A line stop's cargo settings: Line.StopConfig, the line editor's per-stop
-- cargo filter. For each cargo type, `load` and `unload` say whether it is
-- loaded / unloaded here and `maxLoad` its maximum share of the capacity
-- (0..1). Replays used to build every stop with an empty config, so a filter
-- set in the line editor was reset on every instance, the originator's
-- included (KNOWN_ISSUES.md, "A stop's load settings are not carried").
--
-- Wire: a suffix of the stop's record, AFTER the numeric fields and BEFORE the
-- waypoint suffix ("~..."), and only when the config is not empty:
--     @<load>:<unload>:<maxLoad>
-- load / unload are one '0'/'1' per cargo type, maxLoad the fractions as %.9g
-- joined by '/'. None of @ : / 0-9 . e + - inf nan is a separator the record
-- or the command line uses (';' ',' '~' '!' space '=').
return function(CM)
    local function flag(v) return v == true or (type(v) == "number" and v ~= 0) end
    local function bits(vec)
        local out = {}
        for i = 1, #vec do out[i] = flag(vec[i]) and "1" or "0" end
        return table.concat(out)
    end
    local function encode(sc)
        if not sc then return "" end
        local load, unload, mx = sc.load, sc.unload, sc.maxLoad
        if not load or not unload or not mx then error("stopConfig without load/unload/maxLoad") end
        local m = {}
        for i = 1, #mx do m[i] = string.format("%.9g", tonumber(mx[i]) or 1) end
        local l, u = bits(load), bits(unload)
        if l == "" and u == "" and #m == 0 then return "" end
        return "@" .. l .. ":" .. u .. ":" .. table.concat(m, "/")
    end
    local function valid(enc)
        local l, u, m = enc:match("^([01]*):([01]*):([^:]*)$")
        if not l then return false end
        for v in m:gmatch("[^/]+") do
            if CM.waitNum(v) == nil then return false end
        end
        return true
    end

    -- the suffix for an engine stop (lineSnapshot); "" for the default config
    function CM.lineStopConfigSuffix(stop)
        return encode(stop.stopConfig)
    end

    -- the slice's " sc=<stop>:<load>:<unload>:<maxLoad>,..." tail (slice lines.inl
    -- WriteLineStopConfig) onto the decoded stop records. Runs BEFORE
    -- lineCaptureWaypoints: the config sits in front of the waypoint suffix.
    function CM.lineCaptureStopConfig(line, stops)
        local tail = line:match(" sc=([^%s]+)")
        if not tail then return end
        for row in tail:gmatch("[^,]+") do
            local s, enc = row:match("^(%d+):(.+)$")
            s = tonumber(s)
            if not s or not stops[s] or not valid(enc) then error("Invalid captured stop config " .. row) end
            stops[s] = stops[s] .. "@" .. enc
        end
    end

    -- { load = {1|0...}, unload = {1|0...}, maxLoad = {number...} } of a wire
    -- record, or nil when it carries none
    function CM.lineReadStopConfig(record)
        local head = tostring(record):match("^[^~]*")
        local enc = head:match("@(.*)$")
        if not enc then return nil end
        if not valid(enc) then error("Invalid stop config " .. enc) end
        local l, u, m = enc:match("^([01]*):([01]*):([^:]*)$")
        local cfg = { load = {}, unload = {}, maxLoad = {} }
        for c in l:gmatch("[01]") do cfg.load[#cfg.load + 1] = (c == "1") and 1 or 0 end
        for c in u:gmatch("[01]") do cfg.unload[#cfg.unload + 1] = (c == "1") and 1 or 0 end
        for v in m:gmatch("[^/]+") do cfg.maxLoad[#cfg.maxLoad + 1] = CM.waitNum(v) end
        return cfg
    end

    -- ---------- quick edits: merging a click onto the edit still on its way ----------
    -- Each tick in the stop's cargo dialog is its own UpdateLine, built by the editor
    -- from the line as the ENGINE holds it. Under lockstep the previous tick has not
    -- landed yet (or the session is paused), so the next one arrives without it, and
    -- the merge used to take the click's whole record: every tick but the last was
    -- undone (2026-09-26: "only gears" came back as every cargo). The merge now goes
    -- part by part, and a cargo filter entry by entry: only what the click changed
    -- against its base replaces what the pending edit holds.

    -- the parts of a stop record: the numeric fields, the filter (without its "@", ""
    -- for none) and the waypoint suffix (with its "~", "" for none)
    function CM.splitStopRecord(rec)
        local pre, wp = tostring(rec or ""):match("^([^~]*)(.*)$")
        local head, cfg = pre:match("^([^@]*)@?(.*)$")
        return head, cfg, wp
    end

    local function cfgParts(cfg)
        local l, u, m = tostring(cfg or ""):match("^([01]*):([01]*):([^:]*)$")
        local L, U, M = {}, {}, {}
        if l then
            for c in l:gmatch("[01]") do L[#L + 1] = c end
            for c in u:gmatch("[01]") do U[#U + 1] = c end
            for v in m:gmatch("[^/]+") do M[#M + 1] = v end
        end
        return { L, U, M }
    end
    -- the value an entry past the end of a vector stands for: what the other
    -- vector holds there most often (the editor fills a default stop's empty
    -- vectors with one value per cargo type), else the game's default ("1": load,
    -- unload, full capacity). Deterministic: a tie is the default, and so is a tail
    -- of fewer than 3 entries, where "most often" says nothing.
    local function tailFill(vec, from, dflt)
        if #vec - from + 1 < 3 then return dflt end
        local n, best, bestN, tie = {}, nil, 0, false
        for i = from, #vec do
            local v = vec[i]
            n[v] = (n[v] or 0) + 1
            if n[v] > bestN then best, bestN, tie = v, n[v], false
            elseif n[v] == bestN and v ~= best then tie = true end
        end
        if not best or tie then return dflt end
        return best
    end
    local function mergeVec(B, C, P)
        if #C == 0 then return (#B == 0) and P or C end   -- the click emptied it: take that
        local n = math.max(#B, #C, #P)
        local fill = tailFill(C, #B + 1, "1")
        local out = {}
        for i = 1, n do
            local b = B[i] or fill
            local c = C[i] or b
            if c ~= b then out[i] = c else out[i] = P[i] or b end
        end
        return out
    end
    local function joinCfg(parts)
        local L, U, M = parts[1], parts[2], parts[3]
        if #L == 0 and #U == 0 and #M == 0 then return "" end
        return table.concat(L) .. ":" .. table.concat(U) .. ":" .. table.concat(M, "/")
    end
    -- base / click / pending filters ("" = none) -> the merged filter
    function CM.mergeStopConfig(b, c, p)
        if c == b then return p end
        if p == b then return c end
        local B, C, P = cfgParts(b), cfgParts(c), cfgParts(p)
        return joinCfg({ mergeVec(B[1], C[1], P[1]), mergeVec(B[2], C[2], P[2]), mergeVec(B[3], C[3], P[3]) })
    end
    -- one stop re-set by a click: base, click and pending records and platform
    -- lists -> the merged record and platforms
    function CM.mergeStopRecord(bRec, cRec, pRec, bAlt, cAlt, pAlt)
        local bh, bc, bw = CM.splitStopRecord(bRec)
        local ch, cc, cw = CM.splitStopRecord(cRec)
        local ph, pc, pw = CM.splitStopRecord(pRec)
        local head = (ch ~= bh) and ch or ph
        local cfg = CM.mergeStopConfig(bc, cc, pc)
        local wp = (cw ~= bw) and cw or pw
        local alt = (cAlt ~= bAlt) and cAlt or pAlt
        return head .. (cfg ~= "" and ("@" .. cfg) or "") .. wp, alt
    end
    -- how many filter entries differ between two records' filters (lineBaseFor:
    -- a tick changes one, so the list it was built from is one away)
    function CM.stopConfigDistance(aRec, bRec)
        local _, ac = CM.splitStopRecord(aRec)
        local _, bc = CM.splitStopRecord(bRec)
        if ac == bc then return 0 end
        local A, B = cfgParts(ac), cfgParts(bc)
        local d = 0
        for k = 1, 3 do
            local x, y = A[k], B[k]
            if #x < #y then x, y = y, x end   -- x the longer; y's missing entries stand for x's tail fill
            local fill = tailFill(x, #y + 1, "1")
            for i = 1, #x do
                if (y[i] or fill) ~= x[i] then d = d + 1 end
            end
        end
        return d
    end
    -- how many stops of a list carry a filter (for the logs)
    function CM.lineStopConfigCount(stops)
        local n = 0
        for rec in tostring(stops or ""):gmatch("[^;]+") do
            local _, cfg = CM.splitStopRecord(rec)
            if cfg ~= "" then n = n + 1 end
        end
        return n
    end

    -- set a new api.type.Line.Stop's config from its wire record. The flags go in
    -- as the integers 1 and 0, as the API documents them ({int,...}), although the
    -- engine keeps them as bits: its setter refuses anything but an integer, a
    -- boolean included ("stack index 3, expected number, received boolean: not an
    -- integer", 2026-09-26 in a game -- every filter was dropped at the replay).
    function CM.lineApplyStopConfig(stop, record)
        local cfg = CM.lineReadStopConfig(record)
        if not cfg then return false end
        local sc = stop.stopConfig
        if not sc then error("the stop has no stopConfig") end
        -- does sc[field] now read back as vals?
        local function holds(field, vals, isFlag)
            local ok, same = pcall(function()
                local vec = sc[field]
                if #vec ~= #vals then return false end
                for i = 1, #vals do
                    if isFlag then
                        if (flag(vec[i]) and 1 or 0) ~= vals[i] then return false end
                    else
                        local x = tonumber(vec[i])
                        if not x or math.abs(x - vals[i]) > 1e-6 then return false end
                    end
                end
                return true
            end)
            return ok and same
        end
        -- In place, and checked by reading back. NEVER assign a Lua list to one of
        -- these fields: the engine's setter takes it unchecked, as its own type, and
        -- reads through a null pointer -- the game died on it (2026-09-26, build 7,
        -- access violation reading 0 at exe+0x154ea2c the moment a filter replayed).
        -- In place, maxLoad is kept; load and unload are bits in the engine and the
        -- script is handed a copy of them, so their entries are lost. That is logged
        -- ("not written"): the flags have no safe route from the script.
        local how, failed = {}, {}
        local function set(field, vals, isFlag)
            if #vals == 0 then return end   -- none shipped: the new stop's default stays
            local ok, err = pcall(function()
                local vec = sc[field]
                for i, v in ipairs(vals) do vec[i] = v end
                sc[field] = vec
            end)
            if ok and holds(field, vals, isFlag) then how[#how + 1] = field .. " in place"; return end
            failed[#failed + 1] = field .. (ok and " (did not read back)" or (" (" .. tostring(err) .. ")"))
        end
        set("load", cfg.load, true)
        set("unload", cfg.unload, true)
        set("maxLoad", cfg.maxLoad, false)
        stop.stopConfig = sc
        if #failed > 0 then error("not written: " .. table.concat(failed, ", ")) end
        return true, table.concat(how, ", ")
    end
end
