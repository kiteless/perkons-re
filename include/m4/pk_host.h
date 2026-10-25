/* M4 host: shared plumbing for M4 mods built together (tools/perkons/m4host.py).
 *
 * Mods use ordinary globals: .bss lives in the patch RAM and is zeroed at boot, before
 * the mods' init functions run and before device.json loads.
 *
 * Config toggles: a mod defines `uint8_t <var>;` and registers it from Python with
 * host.toggle(key, json_key, var). The host flips it on that config-page key, marks the
 * config for saving, lights the key's LED, and stores it in device.json.
 *
 * FX chain (when a mod calls host.fx()): the stock SAI3 callbacks call pk4_fx_process,
 * which calls pk_fx_engine. Every hook below has a weak default, so FX mods build alone
 * or together; a mod overrides a hook by defining it.
 */
#pragma once
#include <stdint.h>
#include "fw_m4.h"

int pk_host_booted(void);               /* boot hook ran (guards calls that come earlier) */

#define PK_FX_NF        ((int)CONST_fx_block_frames)   /* stereo frames per block, L used */
#define PK_FX_BUF_LEN   32768
extern int16_t pk_fx_buf[PK_FX_BUF_LEN];               /* 64 KB, owned by the running engine */

void pk_fx_engine(const int16_t *in, int16_t *out);    /* default: pk_fx_delay */
void pk_fx_delay(const int16_t *in, int16_t *out);     /* default: stock BBD */
void pk_fx_reset(void);                 /* engine switched, buffers cleared; default: nothing */
int pk_fx_freeze_engaged(void);         /* freeze held now; default 0 */
int pk_fx_switch_is_freeze(void);       /* 2-way switch is freeze, not SHORT/LONG; default 0 */
