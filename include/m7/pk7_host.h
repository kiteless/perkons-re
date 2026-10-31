/* M7 host: shared plumbing for M7 mods built together (tools/perkons/m7host.py).
 *
 * Mods use ordinary globals: .bss lives at the top of the VOICE area and is zeroed at
 * boot (after the stock wire_voices, before the mods' inits and before main inits the
 * voices). Config messages registered with host.message(name, handler) arrive at
 * `void handler(const uint8_t *buf, uint32_t len)`; their type is PK_MSG_<NAME> in both
 * cores' builds. Hooks chain as on the M4: continue with PK_NEXT(hook), and run only
 * once the host has booted. */
#pragma once
#include <stdint.h>
#include "fw_m7.h"

int pk7_host_booted(void);

#define PK_NEXT(hook)   pk_next_##hook
