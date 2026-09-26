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

    -- { load = {bool...}, unload = {bool...}, maxLoad = {number...} } of a wire
    -- record, or nil when it carries none
    function CM.lineReadStopConfig(record)
        local head = tostring(record):match("^[^~]*")
        local enc = head:match("@(.*)$")
        if not enc then return nil end
        if not valid(enc) then error("Invalid stop config " .. enc) end
        local l, u, m = enc:match("^([01]*):([01]*):([^:]*)$")
        local cfg = { load = {}, unload = {}, maxLoad = {} }
        for c in l:gmatch("[01]") do cfg.load[#cfg.load + 1] = (c == "1") end
        for c in u:gmatch("[01]") do cfg.unload[#cfg.unload + 1] = (c == "1") end
        for v in m:gmatch("[^/]+") do cfg.maxLoad[#cfg.maxLoad + 1] = CM.waitNum(v) end
        return cfg
    end

    -- set a new api.type.Line.Stop's config from its wire record. Booleans, not
    -- 0/1: the flags are a vector<bool>, and a Lua 0 converts to true.
    function CM.lineApplyStopConfig(stop, record)
        local cfg = CM.lineReadStopConfig(record)
        if not cfg then return false end
        local sc = stop.stopConfig
        if not sc then error("the stop has no stopConfig") end
        local function fill(field, vals)
            local vec = sc[field]
            if not vec then error("stopConfig has no " .. field) end
            for i, v in ipairs(vals) do vec[i] = v end
            sc[field] = vec
        end
        fill("load", cfg.load)
        fill("unload", cfg.unload)
        fill("maxLoad", cfg.maxLoad)
        stop.stopConfig = sc
        return true
    end
end
