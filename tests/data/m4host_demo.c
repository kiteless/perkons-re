/* two config toggles (one in AXI SRAM) and an init, for tests/test_m4host.py */
#include <stdint.h>
#include "pk_host.h"

uint8_t pk_demo_a;
PK_AXI uint8_t pk_demo_b;
PK_AXI uint32_t pk_demo_axi_words[4];
uint32_t pk_demo_inited;

void pk_demo_init(void)
{
    pk_demo_inited = 0x600d;
}
