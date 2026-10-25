/* two config toggles and an init, for tests/test_m4host.py */
#include <stdint.h>
#include "pk_host.h"

uint8_t pk_demo_a, pk_demo_b;
uint32_t pk_demo_inited;

void pk_demo_init(void)
{
    pk_demo_inited = 0x600d;
}
