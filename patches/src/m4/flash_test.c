/* Flash test: did the bootloader write the flash sectors that stock firmware never uses?
 *
 * The image fills, in each core's segment, everything after the firmware and the mods'
 * code with an address-dependent pattern, up to the end of the core's flash region.
 * Whenever the firmware saves its settings, the sectors that stock never writes
 * (PK_FT_B1_LO..PK_FT_B1_HI in bank 1, PK_FT_B2_LO..PK_FT_B2_HI in bank 2) are read back
 * and FLASHTST.TXT (card root) gives a line per 128 KB sector. */
#include <stdint.h>
#include "pk_host.h"

#define SECTOR 0x20000u

static char txt[640];

static uint32_t pattern(uint32_t a)
{
    return (a * 0x9e3779b1u) ^ 0x5a5aa5a5u;
}

static int check(int n, uint32_t lo, uint32_t hi, int bank, uint32_t *bad)
{
    for (uint32_t s = lo; s < hi; s += SECTOR) {
        uint32_t differ = 0, erased = 0;
        for (uint32_t a = s; a < s + SECTOR; a += 4) {
            uint32_t v = FW_U32(a);
            if (v != pattern(a)) {
                differ++;
                if (v == 0xffffffffu)
                    erased++;
            }
        }
        *bad += differ;
        if (differ)
            n += fw_snprintf(txt + n, sizeof txt - n, "0x%08x bank %d sector %u: BAD, %u words differ (%u erased)\r\n",
                             (unsigned)s, bank, (unsigned)((s & 0xfffffu) / SECTOR), (unsigned)differ, (unsigned)erased);
        else
            n += fw_snprintf(txt + n, sizeof txt - n, "0x%08x bank %d sector %u: OK\r\n",
                             (unsigned)s, bank, (unsigned)((s & 0xfffffu) / SECTOR));
    }
    return n;
}

void pk_flashtest_report(void)
{
    uint32_t bad = 0;
    int n = fw_snprintf(txt, sizeof txt, "Flash test: sectors stock firmware never writes\r\n");
    n = check(n, PK_FT_B1_LO, PK_FT_B1_HI, 1, &bad);
    n = check(n, PK_FT_B2_LO, PK_FT_B2_HI, 2, &bad);
    n += fw_snprintf(txt + n, sizeof txt - n, bad ? "RESULT: FAIL\r\n" : "RESULT: ALL OK\r\n");
    void *fil = (void *)(uintptr_t)SYM_json_file;
    unsigned written;
    if (fw_f_open(fil, "FLASHTST.TXT", FW_FA_WRITE_NEW) == 0) {
        fw_f_write(fil, txt, (unsigned)n, &written);
        fw_f_close(fil);
    }
}
