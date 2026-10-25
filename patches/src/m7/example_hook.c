/* Template for a C patch: wraps one firmware call and changes nothing.
 *
 * Hook: main()'s `bl wire_voices` (0x08027c9e) -> pk_example_wire.
 *
 * Rules for cave code (enforced by tools/perkons/cbuild.py):
 *   - no initialized or zero-initialized globals (.data/.bss): the firmware's startup
 *     code doesn't know about the cave. Keep state at a fixed RAM address you own.
 *   - call firmware functions through the FW_CALL macros in include/<core>/fw_*.h
 *   - functions called from a hooked `bl` get the original call's registers, so give
 *     them the original function's signature.
 */
#include <stdint.h>
#include "fw_m7.h"

void pk_example_wire(void)
{
    fw_wire_voices();   /* the call we replaced; add behaviour before or after it */
}
