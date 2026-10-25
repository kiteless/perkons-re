/* M4 host: weak defaults for the FX hooks (own file, so callers can't inline them). */
#include <stdint.h>
#include "pk_host.h"

__attribute__((weak)) void pk_fx_engine(const int16_t *in, int16_t *out)
{
    pk_fx_delay(in, out);
}

__attribute__((weak)) void pk_fx_delay(const int16_t *in, int16_t *out)
{
    fw_fx_bbd_process(in, out);
}

__attribute__((weak)) void pk_fx_reset(void)
{
}

__attribute__((weak)) int pk_fx_freeze_engaged(void)
{
    return 0;
}

__attribute__((weak)) int pk_fx_switch_is_freeze(void)
{
    return 0;
}
