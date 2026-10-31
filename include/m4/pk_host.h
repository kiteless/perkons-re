/* M4 host: shared plumbing for M4 mods built together (tools/perkons/m4host.py).
 *
 * Mods use ordinary globals: .bss lives in the patch RAM (D2 SRAM, fast) and is zeroed at
 * boot, before the mods' init functions run and before the settings files load. Globals
 * marked PK_AXI live in AXI SRAM instead (~111 KB, a few cycles slower per access, also
 * zeroed at boot). Rule: what the audio path touches per sample stays in .bss; settings,
 * control-rate state and bulk data go in PK_AXI. Never share PK_AXI data with the M7 (its
 * data cache may not see M4 writes); use the IPC streams.
 *
 * Settings: host.setting(json_key, var) stores a uint8_t number in system/mods.json too
 * (no UI of its own; the mod sets the default in its init).
 *
 * Config toggles: a mod defines `uint8_t <var>;` and registers it from Python with
 * host.toggle(key, json_key, var). The host flips it on that config-page key, marks the
 * config for saving, lights the key's LED, and stores it in system/mods.json (its own
 * file, saved whenever the firmware saves system/device.json; device.json stays stock).
 *
 * FX chain (when a mod calls host.fx()): the stock SAI3 callbacks call pk4_fx_process,
 * which calls pk_fx_engine. Every hook below has a weak default, so FX mods build alone
 * or together; a mod overrides a hook by defining it.
 */
#pragma once
#include <stdint.h>
#include "fw_m4.h"

#define PK_AXI          __attribute__((section(".pk_axi")))

int pk_host_booted(void);               /* boot hook ran (guards calls that come earlier) */

/* Hooks registered with h.redirect_call / redirect_branch / replace_word (a function
 * pointer) chain: a hook continues with PK_NEXT(itself), the next mod's hook or the stock
 * function, declared with the hook's own prototype:
 *     uint8_t *PK_NEXT(pk_my_vs)(int track);
 *     uint8_t *pk_my_vs(int track) { ... return PK_NEXT(pk_my_vs)(track); }
 * Hooks only run once the host has booted; before that the firmware calls stock. */
#define PK_NEXT(hook)   pk_next_##hook

#define PK_FX_NF        ((int)CONST_fx_block_frames)   /* stereo frames per block, L used */
#define PK_FX_BUF_LEN   16384
extern int16_t pk_fx_buf[PK_FX_BUF_LEN];               /* 32 KB, owned by the running engine */

void pk_fx_engine(const int16_t *in, int16_t *out);    /* default: pk_fx_delay */
void pk_fx_delay(const int16_t *in, int16_t *out);     /* default: stock BBD */
void pk_fx_reset(void);                 /* engine switched, buffers cleared; default: nothing */
int pk_fx_freeze_engaged(void);         /* freeze held now; default 0 */
int pk_fx_switch_is_freeze(void);       /* 2-way switch is freeze, not SHORT/LONG; default 0 */
