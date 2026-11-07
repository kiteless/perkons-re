/* Card bench: measurements for a sampler that streams from the SD card.
 *
 *  1. D3 canary: the D3 SRAM no firmware code references (PK_D3_START..PK_D3_END) is
 *     filled with an address-dependent pattern at boot; each report says what changed.
 *  2. How long the M4 is held: every pattern save, kit save, bank switch and sample load
 *     is timed (milliseconds): count, last, longest since power-on; and the gaps between
 *     passes of the main loop (where streaming would refill its buffers), as a histogram.
 *  3. The card: a large file (BENCH.WAV in the card root, else SAMPLES/1.wav) read in
 *     4 KB chunks, straight through and at random places, and the time to open a file
 *     (bank 1's SAMPLES/1.wav .. 64.wav, mostly missing).
 *
 * Whenever the firmware saves its settings, BENCH.TXT (card root) gets the results. The
 * reads use the firmware's JSON file object and 4 KB JSON buffer, free once the settings
 * are saved; the report is written from that buffer too, since the card's DMA only
 * reaches AXI SRAM (a whole-sector write straight from D2 RAM fails). Times below a millisecond come from the M4's cycle counter, calibrated
 * against the millisecond tick over the straight read. */
#include <stdint.h>
#include "pk_host.h"

#define CHUNK       4096u
#define SEQ_MAX     (2u * 1024 * 1024)                  /* read at most 2 MB straight */
#define RANDOM_N    64
#define OPEN_N      64
#define BLOCK       1024u                               /* one canary map character */

#define DEMCR       FW_U32(0xe000edfcu)
#define DWT_CTRL    FW_U32(0xe0001000u)
#define DWT_CYCCNT  FW_U32(0xe0001004u)
#define TICK        FW_U32(SYM_hal_tick)                /* ms since boot (SysTick) */
#define FIL         ((void *)(uintptr_t)SYM_json_file)
#define BUF         ((uint8_t *)(uintptr_t)SYM_json_buf)

_Static_assert(CHUNK <= CONST_json_buf_size, "a chunk fits the JSON buffer");

typedef struct {
    uint32_t count, last, max;                          /* ms */
} timing_t;

enum { T_PAT_SAVE, T_KIT_SAVE, T_BANK, T_SAMPLES, T_N };
static const char T_NAME[T_N][16] = {"pattern save", "kit save", "bank switch", "sample load"};
static timing_t timing[T_N];
static uint32_t reports, rng;                           /* .bss only: no startup code in the cave */

/* main loop passes: gaps between them (ms), counted up to each limit */
#define GAPS 9
static const uint16_t GAP_LIMIT[GAPS] = {1, 2, 5, 10, 20, 50, 100, 200, 0xffff};
static uint32_t gap_count[GAPS], passes, gap_max, gap_max_at, last_pass, first_pass;
static char txt[1536];

static uint32_t pattern(uint32_t a)
{
    return (a * 0x9e3779b1u) ^ 0xd3d3c0a1u;
}

void pk_bench_init(void)
{
    DEMCR |= 1u << 24;                                  /* TRCENA: the cycle counter runs */
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1u;
    rng = 0x2545f491u;
    for (uint32_t a = PK_D3_START; a < PK_D3_END; a += 4)
        FW_U32(a) = pattern(a);
}

static void timed(int which, uint32_t t0)
{
    uint32_t ms = TICK - t0;
    timing_t *t = &timing[which];
    t->count++;
    t->last = ms;
    if (ms > t->max)
        t->max = ms;
}

/* chain links, first in their chains: they time everything the save or load does */
int PK_NEXT(pk_bench_pat_save)(uint8_t *hdr, int bank, int idx);
int PK_NEXT(pk_bench_kit_save)(int bank, int kit);
void PK_NEXT(pk_bench_switch_bank)(int bank);
void PK_NEXT(pk_bench_load_samples)(int bank);
void PK_NEXT(pk_bench_loop)(void);

/* once per main loop pass */
void pk_bench_loop(void)
{
    uint32_t now = TICK;
    if (passes++) {
        uint32_t gap = now - last_pass;
        int i = 0;
        while (gap > GAP_LIMIT[i])
            i++;
        gap_count[i]++;
        if (gap > gap_max) {
            gap_max = gap;
            gap_max_at = now;
        }
    } else {
        first_pass = now;
    }
    last_pass = now;
    PK_NEXT(pk_bench_loop)();
}

int pk_bench_pat_save(uint8_t *hdr, int bank, int idx)
{
    uint32_t t0 = TICK;
    int r = PK_NEXT(pk_bench_pat_save)(hdr, bank, idx);
    timed(T_PAT_SAVE, t0);
    return r;
}

int pk_bench_kit_save(int bank, int kit)
{
    uint32_t t0 = TICK;
    int r = PK_NEXT(pk_bench_kit_save)(bank, kit);
    timed(T_KIT_SAVE, t0);
    return r;
}

void pk_bench_switch_bank(int bank)
{
    uint32_t t0 = TICK;
    PK_NEXT(pk_bench_switch_bank)(bank);
    timed(T_BANK, t0);
}

void pk_bench_load_samples(int bank)
{
    uint32_t t0 = TICK;
    PK_NEXT(pk_bench_load_samples)(bank);
    timed(T_SAMPLES, t0);
}

/* ---- the report ------------------------------------------------------------------ */

typedef struct {
    uint32_t n, min, max, sum;                          /* cycles (sums stay far below 2^32) */
} stat_t;

static void clear(stat_t *s)                            /* (= {0} would call memset) */
{
    s->n = s->min = s->max = s->sum = 0;
}

static void add(stat_t *s, uint32_t cyc)
{
    if (!s->n || cyc < s->min)
        s->min = cyc;
    if (cyc > s->max)
        s->max = cyc;
    s->sum += cyc;
    s->n++;
}

static int n_;
#define PUT(...) (n_ += fw_snprintf(txt + n_, n_ < (int)sizeof txt ? sizeof txt - n_ : 0, __VA_ARGS__))

/* cycles -> microseconds, once calibrated (cpm: cycles per ms; 0 = raw cycles) */
static void put_stat(const char *what, const stat_t *s, uint32_t cpm)
{
    if (!s->n) {
        PUT("%s: none\r\n", what);
        return;
    }
    uint32_t avg = s->sum / s->n, cpu = cpm / 1000;    /* cycles per microsecond */
    if (cpu)
        PUT("%s (%u): min %u us, avg %u us, max %u us\r\n", what, (unsigned)s->n,
            (unsigned)(s->min / cpu), (unsigned)(avg / cpu), (unsigned)(s->max / cpu));
    else
        PUT("%s (%u): min %u, avg %u, max %u cycles\r\n", what, (unsigned)s->n,
            (unsigned)s->min, (unsigned)avg, (unsigned)s->max);
}

static uint32_t random32(void)
{
    rng ^= rng << 13;
    rng ^= rng >> 17;
    rng ^= rng << 5;
    return rng;
}

static void card(void)
{
    static const char names[3][24] = {"BENCH.WAV", "SAMPLES/1.wav", "BANKS/00/SAMPLES/1.wav"};
    const char *name = 0;
    for (unsigned i = 0; i < 3 && !name; i++)
        if (fw_f_open(FIL, names[i], FW_FA_READ) == 0)
            name = names[i];
    if (!name) {
        PUT("card: no BENCH.WAV or SAMPLES/1.wav to read\r\n");
        return;
    }
    uint32_t size = FW_U32((uintptr_t)FIL + FW_FIL_SIZE);
    PUT("card: %s, %u bytes\r\n", name, (unsigned)size);

    /* straight through, 4 KB at a time */
    stat_t chunk, rnd, open_hit, open_miss;
    clear(&chunk);
    clear(&rnd);
    clear(&open_hit);
    clear(&open_miss);
    uint32_t total = 0, t0 = TICK, c0 = DWT_CYCCNT;
    unsigned got;
    while (total < SEQ_MAX) {
        uint32_t c = DWT_CYCCNT;
        if (fw_f_read(FIL, BUF, CHUNK, &got) != 0 || !got)
            break;
        add(&chunk, DWT_CYCCNT - c);
        total += got;
    }
    uint32_t ms = TICK - t0, cyc = DWT_CYCCNT - c0;
    uint32_t cpm = ms >= 20 ? cyc / ms : 0;             /* calibration: cycles per ms */
    PUT("straight read: %u bytes in %u ms", (unsigned)total, (unsigned)ms);
    if (ms)
        PUT(" = %u KB/s", (unsigned)(total / 1024 * 1000 / ms));
    PUT("\r\n");
    put_stat("  each 4 KB", &chunk, cpm);

    /* at random places: a seek, then 4 KB (sector-aligned, inside the file) */
    if (size > 2 * CHUNK) {
        for (int i = 0; i < RANDOM_N; i++) {
            uint32_t ofs = (random32() % (size - CHUNK)) & ~511u;
            uint32_t c = DWT_CYCCNT;
            if (fw_f_lseek(FIL, ofs) != 0 || fw_f_read(FIL, BUF, CHUNK, &got) != 0)
                break;
            add(&rnd, DWT_CYCCNT - c);
        }
    }
    put_stat("random 4 KB (seek + read)", &rnd, cpm);
    fw_f_close(FIL);

    /* opening files: a bank's sample folder, 1..64 (missing ones fail after the search) */
    char path[32];
    for (int i = 1; i <= OPEN_N; i++) {
        fw_snprintf(path, sizeof path, "BANKS/00/SAMPLES/%d.wav", i);
        uint32_t c = DWT_CYCCNT;
        int r = fw_f_open(FIL, path, FW_FA_READ);
        uint32_t d = DWT_CYCCNT - c;
        if (r == 0) {
            add(&open_hit, d);
            fw_f_close(FIL);
        } else {
            add(&open_miss, d);
        }
    }
    put_stat("open, found", &open_hit, cpm);
    put_stat("open, missing", &open_miss, cpm);
    if (cpm)
        PUT("M4 clock: %u kHz\r\n", (unsigned)cpm);
    else
        PUT("M4 clock: not calibrated (straight read under 20 ms): times in cycles\r\n");
}

static void d3(void)
{
    const uint32_t nblocks = (PK_D3_END - PK_D3_START + BLOCK - 1) / BLOCK;
    uint32_t changed = 0, first = 0, last = 0;
    char map[64];
    for (uint32_t b = 0; b < nblocks && b < sizeof map; b++)
        map[b] = '.';
    for (uint32_t a = PK_D3_START; a < PK_D3_END; a += 4) {
        if (FW_U32(a) != pattern(a)) {
            if (!changed++)
                first = a;
            last = a;
            map[(a - PK_D3_START) / BLOCK] = 'X';
        }
    }
    PUT("D3 canary 0x%08x-0x%08x: changed words %u", (unsigned)PK_D3_START, (unsigned)PK_D3_END,
        (unsigned)changed);
    if (changed)
        PUT(" (first 0x%08x, last 0x%08x)", (unsigned)first, (unsigned)last);
    PUT("\r\n  map, 1 KB per character ('.' intact, 'X' changed): ");
    for (uint32_t b = 0; b < nblocks && b < sizeof map && n_ < (int)sizeof txt - 4; b++)
        txt[n_++] = map[b];
    PUT("\r\n");
}

void pk_bench_report(void)
{
    n_ = 0;
    reports++;
    PUT("Card bench, report %u since power-on (%u s)\r\n\r\n", (unsigned)reports, (unsigned)(TICK / 1000));
    d3();
    PUT("\r\nM4 held by (ms):\r\n");
    for (int i = 0; i < T_N; i++)
        PUT("  %s: %u times, last %u, longest %u\r\n", T_NAME[i], (unsigned)timing[i].count,
            (unsigned)timing[i].last, (unsigned)timing[i].max);
    PUT("\r\nmain loop: %u passes", (unsigned)passes);
    if (passes > 1 && last_pass > first_pass)
        PUT(", %u per second", (unsigned)((passes - 1) / ((last_pass - first_pass + 999) / 1000)));
    PUT("; longest gap %u ms (at %u s)\r\n  gaps (ms):", (unsigned)gap_max, (unsigned)(gap_max_at / 1000));
    for (int i = 0; i < GAPS; i++) {
        if (GAP_LIMIT[i] == 0xffff)
            PUT(" >%u: %u", (unsigned)GAP_LIMIT[i - 1], (unsigned)gap_count[i]);
        else
            PUT(" <=%u: %u", (unsigned)GAP_LIMIT[i], (unsigned)gap_count[i]);
    }
    PUT("\r\n\r\n");
    card();
    if (n_ > (int)sizeof txt)
        n_ = sizeof txt;
    _Static_assert(sizeof txt <= CONST_json_buf_size, "the report fits the JSON buffer");
    pk_copy(BUF, txt, (unsigned)n_);                    /* AXI SRAM: the card's DMA reaches it */
    unsigned written;
    if (fw_f_open(FIL, "BENCH.TXT", FW_FA_WRITE_NEW) == 0) {
        fw_f_write(FIL, BUF, (unsigned)n_, &written);
        fw_f_close(FIL);
    }
}
