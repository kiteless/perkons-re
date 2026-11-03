/* two UI pages, for tests/test_m4host.py (TestPages) */
#include <stdint.h>
#include "pk_host.h"

uint8_t pk_pg_numbers[2];           /* PK_PAGE_ALPHA, PK_PAGE_BETA */
uint32_t pk_pg_log[8];              /* 1 enter, 2 leave, 3 key handled, 4 draw */
uint32_t pk_pg_n;

static void note(uint32_t what)
{
    if (pk_pg_n < 8 && (pk_pg_n == 0 || pk_pg_log[pk_pg_n - 1] != what))
        pk_pg_log[pk_pg_n++] = what;
}

void pk_pg_init(void)
{
    pk_pg_numbers[0] = PK_PAGE_ALPHA;
    pk_pg_numbers[1] = PK_PAGE_BETA;
}

int pk_pg_key(const uint8_t *evt)
{
    if (evt[0] >= 0x40)
        return 0;                   /* the rest: stock */
    note(3);
    return 1;
}

void pk_pg_draw(void)
{
    note(4);
    fw_set_led(0, 0x80);
}

void pk_pg_enter(void)
{
    note(1);
}

void pk_pg_leave(void)
{
    note(2);
}
