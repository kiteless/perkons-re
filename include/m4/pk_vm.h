/* voice map's M4 interface for engine mods (tools/perkons/voicemap.py) */
#pragma once
#include <stdint.h>

/* the engine voice v (0-3) runs now: 0-3 the stock engines, 4- the extra engines (their
 * slot - 1, as the engine page's column - 1), or -1 */
int pk_vm_engine(int v);

/* Kit slots: an engine keeps its per-kit sound in the voice map's table, a slot per kit and
 * voice, instead of a table of its own (declare the record's size: 'kit_bytes' in its
 * voicemap.engines entry). The slot belongs to the engine the voice has in that kit: a voice
 * that changes engine gets an empty one (all 0), so an engine's "nothing saved" is all 0.
 * At a bank load the engine map is read first: an engine's kit restore fills the voices
 * that are its own (pk_vm_kit_slot not 0) and leaves the others alone. */

/* the engine voice v (0-3) has in kit (0-63), as saved or chosen on the engine page; -1 */
int pk_vm_kit_engine(int kit, int v);
/* voice v's slot in kit if the voice runs `engine` there (the pk_vm_engine numbering) and
 * the slot holds `bytes`; else 0 */
uint8_t *pk_vm_kit_slot(int kit, int v, int engine, unsigned bytes);
