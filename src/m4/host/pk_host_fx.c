/* M4 host: FX process function and the shared FX buffer. See include/m4/pk_host.h. */
#include <stdint.h>
#include "pk_host.h"

int16_t pk_fx_buf[PK_FX_BUF_LEN];

/* installed as fx_process_fnptr; called by the stock SAI3 DMA callbacks every block */
void pk4_fx_process(const int16_t *in, int16_t *out)
{
    if (!pk_host_booted()) {
        fw_fx_bbd_process(in, out);
        return;
    }
    pk_fx_engine(in, out);
}
