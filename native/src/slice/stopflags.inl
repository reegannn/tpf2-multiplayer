// stopflags.inl -- part of tpf2_slice.dll: included by slice_hook.cpp after add_hook.inl (it needs GameNewBytes).
// A replayed line stop's cargo flags (Line.StopConfig load / unload), written into the command's Line.
//
// WHY THE SLICE. A stop's cargo filter is three vectors at Stop+0x50 (ReadStopConfig in
// lines.inl): load and unload are vector<bool>, maxLoad a vector<float>. The capture reads
// all three and the mod ships them with the stop, but the script cannot set the two flag
// vectors on the Line it builds for the replay (three game tests, 2026-09-26):
//   - written in place they are lost: the engine keeps them as bits and hands the script a
//     copy, so the line went out with no flags ("every cargo ticked" in the line editor);
//   - a Lua list assigned to one crashes the game: the setter takes it unchecked as its own
//     type and reads through a null pointer (access violation reading 0 at exe+0x154ea2c).
// maxLoad, a plain vector, the script sets in place (stopconfig.lua).
//
// HOW. Right before api.cmd.make.updateLine the Lua writes lockstep_lcfg_<x>.txt
//     <line> <seq> <k> <stop>:<load|->:<unload|-> ...      ("-" = leave that vector alone)
// and blanks it after the call (CM.lineFlagsRequest / CM.lineFlagsDone) -- the handoff
// lockstep_lassign_<x>.txt already uses. The factory hook runs inside that call, on the
// script's thread; at its entry, where ApplyLineAssignAtReplay edits the same Line's
// platforms, this writes the flags into the Line in place, before the factory takes the
// stops. Every instance replays the same request at the same step, so every game's line
// gets the same flags.
//
// WHAT IS WRITTEN. The MSVC vector<bool>: { uint32_t* begin, *end, *cap; size_t bits },
// bit k in bit k%32 of word k/32 -- the layout ReadStopConfig reads, and that read the
// game's own filters correctly in every game test. A new buffer comes from the game's own
// operator new (GameNewBytes, checked against build 35924), so the game's std::allocator
// frees it through its operator delete like any buffer of its own. Only an EMPTY vector
// (all four fields zero: what a script-built Stop holds) or a well-formed one whose buffer
// already fits is written; anything else is left alone and logged. Every write is read
// back through ReadStopConfig and compared.

static long g_lcfgSeen = 0;             // the last lockstep_lcfg seq applied
static char g_lcfgLine[40000];          // one request line
static char g_lcfgLoad[4100], g_lcfgUnload[4100];
static const size_t STOPFLAGS_MAX_BITS = 4096;   // 512 bytes of words: far under GameNewBytes' 4096-byte limit

// bits ("0"/"1" only) into the MSVC vector<bool> at `at`. PODs only (it uses __try).
// 1 written, 0 left alone (logged), -1 faulted.
static int WriteFlagBits(uint8_t* at, const char* bits, size_t n, int stop, const char* what)
{
    const size_t words = (n + 31) / 32;
    __try {
        uint64_t wb = 0, we = 0, wc = 0, nb = 0;
        memcpy(&wb, at, 8); memcpy(&we, at + 0x08, 8); memcpy(&wc, at + 0x10, 8); memcpy(&nb, at + 0x18, 8);
        uint32_t* buf = nullptr;
        uint64_t cap = 0;
        if (wb == 0 && we == 0 && wc == 0 && nb == 0) {
            buf = (uint32_t*)GameNewBytes(words * 4);
            if (!buf) {
                Log("[stopflags] stop %d %s: the game's allocator gave no buffer -- not written\n", stop, what);
                return 0;
            }
            cap = (uint64_t)buf + words * 4;
        } else if (IsHeapPtr(wb) && we >= wb && wc >= we && (we - wb) % 4 == 0 && (wc - wb) % 4 == 0
                   && (we - wb) == ((nb + 31) / 32) * 4 && (wc - wb) >= words * 4
                   && Readable((void*)wb, (size_t)(wc - wb))) {
            buf = (uint32_t*)wb;
            cap = wc;
        } else {
            Log("[stopflags] stop %d %s: the vector is not empty and not reusable (%llx..%llx cap %llx, %llu bits) -- left alone\n",
                stop, what, (unsigned long long)wb, (unsigned long long)we, (unsigned long long)wc, (unsigned long long)nb);
            return 0;
        }
        for (size_t k = 0; k < words; k++) buf[k] = 0;
        for (size_t k = 0; k < n; k++) if (bits[k] == '1') buf[k / 32] |= 1u << (k % 32);
        const uint64_t nbeg = (uint64_t)buf, nend = nbeg + words * 4, nbits = (uint64_t)n;
        memcpy(at, &nbeg, 8); memcpy(at + 0x08, &nend, 8); memcpy(at + 0x10, &cap, 8); memcpy(at + 0x18, &nbits, 8);
        return 1;
    }
    __except (EXCEPTION_EXECUTE_HANDLER) { return -1; }
}

static bool FlagBitsValid(const char* bits, size_t* n)
{
    *n = strlen(bits);
    if (*n == 0 || *n > STOPFLAGS_MAX_BITS) return false;
    for (size_t k = 0; k < *n; k++) if (bits[k] != '0' && bits[k] != '1') return false;
    return true;
}

// The part `field` (0 load, 1 unload) of ReadStopConfig's "<load>:<unload>:<maxLoad>".
static std::string CfgPart(const std::string& cfg, int field)
{
    size_t a = 0;
    for (int i = 0; i < field; i++) {
        a = cfg.find(':', a);
        if (a == std::string::npos) return std::string();
        a++;
    }
    const size_t b = cfg.find(':', a);
    return cfg.substr(a, b == std::string::npos ? std::string::npos : b - a);
}

static void ApplyStopFlagsAtReplay(int32_t entity, uint64_t line)
{
    ReadInstance();
    if (!g_instance[0]) return;
    char p[MAX_PATH];
    snprintf(p, sizeof(p), "%slockstep_lcfg_%s.txt", g_dataDir, g_instance);
    WIN32_FILE_ATTRIBUTE_DATA fa;
    if (!GetFileAttributesExA(p, GetFileExInfoStandard, &fa)) return;
    if (fa.nFileSizeLow == 0) return;
    FILETIME nowFt;
    GetSystemTimeAsFileTime(&nowFt);
    const uint64_t wrote = ((uint64_t)fa.ftLastWriteTime.dwHighDateTime << 32) | fa.ftLastWriteTime.dwLowDateTime;
    const uint64_t now = ((uint64_t)nowFt.dwHighDateTime << 32) | nowFt.dwLowDateTime;
    if (now > wrote && now - wrote > 5ULL * 10000000ULL) return;   // stale: not this call's
    FILE* f = _fsopen(p, "r", _SH_DENYNO);
    if (!f) return;
    const bool got = fgets(g_lcfgLine, sizeof(g_lcfgLine), f) != nullptr;
    fclose(f);
    if (!got) return;
    long lid = 0, seq = 0;
    int k = 0, off = 0;
    if (sscanf(g_lcfgLine, "%ld %ld %d%n", &lid, &seq, &k, &off) != 3 || k < 0) {
        Log("[stopflags] request unreadable: %.120s\n", g_lcfgLine);
        return;
    }
    if (lid != (long)entity || seq == g_lcfgSeen) return;
    g_lcfgSeen = seq;

    // the stops vector exactly as the capture reads it (DecodeLineAt: +0x00, 0xa8 per stop)
    uint64_t sb = 0;
    const uint64_t span = ReadVec(line, &sb, LINE_ANY_SPAN);
    if (span == 0 || (span % 0xa8) != 0) {
        Log("[stopflags] LUPDATE replay line=%d seq=%ld: stops vector unreadable (span %llu) -- %d stop(s) of cargo flags NOT written\n",
            (int)entity, seq, (unsigned long long)span, k);
        return;
    }
    const int n = (int)(span / 0xa8);
    int written = 0, failed = 0;
    const char* q = g_lcfgLine + off;
    for (int t = 0; t < k; t++) {
        int idx = 0, used = 0;
        if (sscanf(q, " %d:%4096[-01]:%4096[-01]%n", &idx, g_lcfgLoad, g_lcfgUnload, &used) != 3) {
            Log("[stopflags] line=%d: request token %d unreadable -- the rest NOT written\n", (int)entity, t + 1);
            failed++;
            break;
        }
        q += used;
        if (idx < 1 || idx > n) {
            Log("[stopflags] line=%d: stop %d is not one of its %d -- NOT written\n", (int)entity, idx, n);
            failed++;
            continue;
        }
        uint8_t* stop = (uint8_t*)sb + (size_t)(idx - 1) * 0xa8;
        const char* want[2] = { g_lcfgLoad, g_lcfgUnload };
        const int at[2] = { 0x50, 0x70 };
        const char* name[2] = { "load", "unload" };
        bool stopOk = true;
        for (int v = 0; v < 2; v++) {
            if (strcmp(want[v], "-") == 0) continue;
            size_t nbits = 0;
            if (!FlagBitsValid(want[v], &nbits)) {
                Log("[stopflags] line=%d stop %d %s: %.40s is not a flag list -- NOT written\n", (int)entity, idx, name[v], want[v]);
                stopOk = false;
                continue;
            }
            const int r = WriteFlagBits(stop + at[v], want[v], nbits, idx, name[v]);
            if (r < 0) Log("[stopflags] line=%d stop %d %s: the write faulted -- NOT written\n", (int)entity, idx, name[v]);
            if (r != 1) stopOk = false;
        }
        // read back exactly as the capture reads a filter, and compare
        std::string cfg;
        const bool read = ReadStopConfig((const uint8_t*)stop, &cfg, idx);
        for (int v = 0; v < 2 && stopOk; v++) {
            if (strcmp(want[v], "-") == 0) continue;
            if (!read || CfgPart(cfg, v) != want[v]) {
                Log("[stopflags] line=%d stop %d %s: MISMATCH after the write (reads %.200s)\n", (int)entity, idx, name[v],
                    read ? cfg.c_str() : "unreadable");
                stopOk = false;
            }
        }
        if (stopOk) written++; else failed++;
    }
    Log("[stopflags] LUPDATE replay line=%d seq=%ld: cargo flags written on %d stop(s), %d failed\n", (int)entity, seq, written, failed);
}
