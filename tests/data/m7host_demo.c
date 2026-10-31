/* a config message, an init and a chained render hook, for tests/test_m7host.py */
#include <stdint.h>
#include "pk7_host.h"

uint32_t pk7_demo_inited;
uint32_t pk7_demo_got;              /* last message: first byte | length << 8 */
uint32_t pk7_demo_renders;

void pk7_demo_init(void)
{
    pk7_demo_inited = 0x600d;
}

void pk7_demo_msg(const uint8_t *buf, uint32_t len)
{
    pk7_demo_got = buf[0] | len << 8;
}

#ifdef PK7_DEMO_RENDER                  /* only when the test registers the hook */
int16_t PK_NEXT(pk7_demo_render)(void *crush);

int16_t pk7_demo_render(void *crush)
{
    pk7_demo_renders++;
    return PK_NEXT(pk7_demo_render)(crush);
}
#endif
