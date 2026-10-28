/* AXI SRAM canary: is the AXI SRAM that no firmware code references really unused?
 *
 * At boot (before the settings and samples load) the region PK_GAP_START..PK_GAP_END is
 * filled with an address-dependent pattern. Whenever the firmware saves its settings,
 * the region is checked and CANARY.TXT (card root) says what was overwritten since boot.
 * The pattern is never refreshed, so each report covers everything since power-on. */
#include <stdint.h>
#include "pk_host.h"

#define BLOCK       1024u                               /* one map character */
#define NBLOCKS     ((PK_GAP_END - PK_GAP_START + BLOCK - 1) / BLOCK)
#define MAP_COLS    64

static uint32_t reports;
static char txt[512];

static uint32_t pattern(uint32_t a)
{
    return (a * 0x9e3779b1u) ^ 0xc0a1c0a1u;
}

void pk_canary_fill(void)
{
    for (uint32_t a = PK_GAP_START; a < PK_GAP_END; a += 4)
        FW_U32(a) = pattern(a);
}

void pk_canary_report(void)
{
    uint32_t changed = 0, first = 0, last = 0;
    char map[NBLOCKS];
    for (uint32_t b = 0; b < NBLOCKS; b++)
        map[b] = '.';
    for (uint32_t a = PK_GAP_START; a < PK_GAP_END; a += 4) {
        if (FW_U32(a) != pattern(a)) {
            if (!changed++)
                first = a;
            last = a;
            map[(a - PK_GAP_START) / BLOCK] = 'X';
        }
    }
    reports++;
    int n = fw_snprintf(txt, sizeof txt,
                        "AXI SRAM canary\r\nregion 0x%08x-0x%08x, filled at power-on\r\n"
                        "report %u since power-on\r\nchanged words: %u\r\n",
                        (unsigned)PK_GAP_START, (unsigned)PK_GAP_END, (unsigned)reports, (unsigned)changed);
    if (changed)
        n += fw_snprintf(txt + n, sizeof txt - n, "first changed: 0x%08x\r\nlast changed: 0x%08x\r\n",
                         (unsigned)first, (unsigned)last);
    n += fw_snprintf(txt + n, sizeof txt - n, "map, 1 KB per character ('.' intact, 'X' changed):\r\n");
    for (uint32_t b = 0; b < NBLOCKS && n < (int)sizeof txt - MAP_COLS - 3; b += MAP_COLS) {
        for (uint32_t i = b; i < b + MAP_COLS && i < NBLOCKS; i++)
            txt[n++] = map[i];
        txt[n++] = '\r';
        txt[n++] = '\n';
    }
    void *fil = (void *)(uintptr_t)SYM_json_file;
    unsigned written;
    if (fw_f_open(fil, "CANARY.TXT", FW_FA_WRITE_NEW) == 0) {
        fw_f_write(fil, txt, (unsigned)n, &written);
        fw_f_close(fil);
    }
}
