/* two hooks on one site and an event subscriber, for tests/test_m4host.py (TestChains) */
#include <stdint.h>
#include "pk_host.h"

uint32_t pk_chain_log[8];           /* who ran, in order: 1 first, 2 second, 3 event */
uint32_t pk_chain_n;

static void note(uint32_t who)
{
    if (pk_chain_n < 8)
        pk_chain_log[pk_chain_n++] = who;
}

void PK_NEXT(pk_chain_first)(uint32_t pwm);
void PK_NEXT(pk_chain_second)(uint32_t pwm);

void pk_chain_first(uint32_t pwm)
{
    note(1);
    PK_NEXT(pk_chain_first)(pwm + 1);
}

void pk_chain_second(uint32_t pwm)
{
    note(2);
    PK_NEXT(pk_chain_second)(pwm + 10);
}

void pk_chain_cleared(void)
{
    note(3);
}
