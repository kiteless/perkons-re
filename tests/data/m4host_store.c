/* a pattern store, for tests/test_m4host.py (TestStore) */
#include <stdint.h>
#include "pk_host.h"

uint8_t pk_st_loaded[64];           /* per pattern: the record's byte, 0xee none */
uint32_t pk_st_len[64];

uint32_t pk_st_save(int bank, int idx, uint8_t *buf, uint32_t max)
{
    (void)max;
    if (idx == 9)
        return 0;                   /* nothing to keep for pattern 10 */
    buf[0] = (uint8_t)(bank * 16 + idx);
    buf[1] = 0x5a;
    return 2;
}

void pk_st_load(int bank, int idx, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    pk_st_len[idx] = len;
    pk_st_loaded[idx] = len ? rec[0] : 0xee;
}
