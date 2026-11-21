/* Voice map, M4 side: each kit chooses the engine of each voice.
 *
 * The four engines are kept with the kit (the M4 host's kit sidecar, KITS/PP.KIX, record
 * VMAP: one nibble per voice); a kit without one plays the stock engines 1, 2, 3, 4. Loading
 * a kit (the KIT page, a bank load, kit-link on a pattern switch) sends its engines to the
 * M7 in order with the triggers, so the next note of each voice plays the kit's engine.
 *
 * Engine page, a UI page of its own (the M4 host's pages): hold KIT and press MOD, from any
 * page (as PATTERN + KIT opens the bank menu). Rows 1-4 = voices 1-4, columns = engines
 * (stock 1-4, then other mods' engines); the LED shows each voice's engine, dim the ones it
 * could have. A step chooses; every other key works as stock: the trigger keys play the
 * voices (the next note sounds the new engine), a page button leaves. Leaving keeps the
 * choice in the kit and writes the kit's sidecar.
 *
 * Engine settings pages: an engine may register an M4 page of its own (the engine's
 * 'page'). Holding a voice's step of that engine for HOLD_MS opens it, with
 * pk_vm_settings_voice the voice (its row); pressing a dim step chooses the engine first,
 * so a long press on it chooses and opens.
 *
 * Kit slots: one table for every engine's per-kit sound, a slot per kit and voice, owned by
 * the engine that voice runs in that kit (kit_map). An engine keeps its sound there
 * (pk_vm_kit_slot) instead of a table of its own, so the table is as big as the largest
 * engine's record, however many engines there are. A voice that changes engine in a kit
 * starts the new one from an empty slot (all 0: the engine's own "nothing saved"); a saved
 * kit keeps each voice's engine and its sound. VMAP is a 'first' store: its record is read
 * before the engines' so they know which voices are theirs. */
#include <stdint.h>
#include "pk_host.h"
#include "pk_engines.h"             /* PK_N_ENGINES, PK_ENGINE_MASK: the engine page's columns */

#define NKITS           64
#define DEFAULT_MAP     0x3210u     /* voice v runs engine v */
#define LED_ON          0x80
#define LED_DIM         0x10
#define HOLD_MS         500         /* a long press on a step: the engine's settings page */

PK_AXI static uint16_t kit_map[NKITS];  /* each kit's engines, a nibble per voice */
PK_AXI static uint16_t cur;             /* the engines playing */
PK_AXI uint8_t pk_vm_settings_voice;    /* the voice an engine's settings page is for */
PK_AXI static uint8_t pressed;          /* the step held down on the page, + 1 (0: none) */
PK_AXI static uint32_t pressed_at;      /* its press, ms (fw_get_tick) */
static const uint8_t engine_page[16] = PK_ENGINE_PAGES;
#if PK_VM_KIT_BYTES
/* the kit slots (STORE: read at kit loads, saves and on the engines' pages only), a section
 * of their own: an owner of their own in the Mod Matrix's memory figures, which grows with
 * the largest engine record */
__attribute__((section(".pk_axi.kit_slots"), aligned(4))) static uint8_t kit_slot[NKITS][4][PK_VM_KIT_BYTES];
#endif

static unsigned engine_of(uint16_t map, int v)
{
    return map >> (4 * v) & 0xfu;
}

/* for other engine mods' M4 code (pk_vm.h): the engine voice v runs now (0-3 the stock
 * engines, 4- the extra engines: slot - 1), or -1 */
int pk_vm_engine(int v)
{
    return v >= 0 && v < 4 ? (int)engine_of(cur, v) : -1;
}

/* for engine mods (pk_vm.h): the engine voice v has in kit (as saved or chosen), or -1 */
int pk_vm_kit_engine(int kit, int v)
{
    return kit >= 0 && kit < NKITS && v >= 0 && v < 4 ? (int)engine_of(kit_map[kit], v) : -1;
}

/* for engine mods (pk_vm.h): voice v's slot in kit, if the voice runs `engine` there and the
 * slot holds `bytes`; else 0 */
uint8_t *pk_vm_kit_slot(int kit, int v, int engine, unsigned bytes)
{
#if PK_VM_KIT_BYTES
    if (bytes <= PK_VM_KIT_BYTES && pk_vm_kit_engine(kit, v) == engine && engine >= 0)
        return kit_slot[kit][v];
#endif
    (void)kit, (void)v, (void)engine, (void)bytes;
    return 0;
}

/* a kit's engines: a voice whose engine changes gets an empty slot */
static void set_kit_map(int kit, uint16_t map)
{
#if PK_VM_KIT_BYTES
    for (int v = 0; v < 4; v++)
        if (engine_of(map, v) != engine_of(kit_map[kit], v))
            for (int i = 0; i < PK_VM_KIT_BYTES; i++)
                kit_slot[kit][v][i] = 0;
#endif
    kit_map[kit] = map;
}

static void send(uint16_t map)
{
    uint8_t m[4];
    for (int v = 0; v < 4; v++)
        m[v] = (uint8_t)engine_of(map, v);
    pk_send_m7(PK_STREAM_VOICE_MAP, PK_MSG_VOICE_MAP, m, 4);
}

void pk_vm_init(void)
{
    for (int k = 0; k < NKITS; k++)
        kit_map[k] = DEFAULT_MAP;
    cur = DEFAULT_MAP;                  /* the kit slots: zeroed at boot with the other PK_AXI */
}

/* kit loads (chained with the other mods' kit hooks): the kit's engines */
void PK_NEXT(pk_vm_kit_load)(int kit);

void pk_vm_kit_load(int kit)
{
    PK_NEXT(pk_vm_kit_load)(kit);
    if (kit < 0 || kit >= NKITS)
        return;
    cur = kit_map[kit];
    send(cur);
}

/* the host's kit sidecar, record "VMAP": u16, a nibble per voice; none = stock engines. A
 * 'first' store: saved before the engines' records (their slots follow the engines saved) */
uint32_t pk_vm_kit_save(int bank, int kit, uint8_t *buf, uint32_t max)
{
    (void)bank;
    set_kit_map(kit, cur);
    if (cur == DEFAULT_MAP || max < 2)
        return 0;
    buf[0] = (uint8_t)cur;
    buf[1] = (uint8_t)(cur >> 8);
    return 2;
}

/* read before the engines' records ('first'): the slots start empty, each engine fills the
 * voices that are its own */
void pk_vm_kit_restore(int bank, int kit, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    kit_map[kit] = len == 2 ? (uint16_t)(rec[0] | rec[1] << 8) : DEFAULT_MAP;
#if PK_VM_KIT_BYTES
    for (int v = 0; v < 4; v++)
        for (int i = 0; i < PK_VM_KIT_BYTES; i++)
            kit_slot[kit][v][i] = 0;
#endif
}

/* KIT + MOD (chained before the stock key handling): the engine page */
int PK_NEXT(pk_vm_key_event)(const uint8_t *evt);

int pk_vm_key_event(const uint8_t *evt)
{
    if (evt[0] == FW_KEY_MOD && evt[1] == FW_EV_DOWN && fw_key_held(FW_KEY_KIT)) {
        fw_set_mode(PK_PAGE_ENGINES);
        return 1;
    }
    return PK_NEXT(pk_vm_key_event)(evt);
}

/* the engine page: a step chooses that row's voice's engine; the KIT and MOD releases are
 * kept from the stock handling (a long hold's release would go to the MAIN page) */
int pk_vm_page_key(const uint8_t *evt)
{
    if (evt[1] != FW_EV_DOWN && evt[1] != FW_EV_UP)
        return 0;                       /* not a key (the panel switches): stock */
    if (evt[0] < 0x40) {
        int v = evt[0] / 16, e = evt[0] % 16;
        if (evt[1] == FW_EV_DOWN && v < 4 && (PK_ENGINE_MASK >> e & 1) && (unsigned)e != engine_of(cur, v)) {
            cur = (uint16_t)((cur & ~(0xfu << (4 * v))) | (unsigned)e << (4 * v));
            send(cur);
        }
        if (evt[1] == FW_EV_DOWN) {     /* timing a long press (the page's own events) */
            pressed = (uint8_t)(evt[0] + 1);
            pressed_at = fw_get_tick();
        } else if (evt[0] + 1 == pressed) {
            pressed = 0;
        }
        return 1;
    }
    return evt[1] == FW_EV_UP && (evt[0] == FW_KEY_KIT || evt[0] == FW_KEY_MOD);
}

void pk_vm_page_draw(void)
{
    if (pressed) {                      /* a long press on a voice's engine: its settings page */
        int v = (pressed - 1) / 16, e = (pressed - 1) % 16;
        if (v < 4 && (unsigned)e == engine_of(cur, v) && engine_page[e] &&
            fw_get_tick() - pressed_at >= HOLD_MS) {
            pressed = 0;                /* once per press */
            pk_vm_settings_voice = (uint8_t)v;
            fw_set_mode(engine_page[e]);
            return;
        }
    }
    for (int k = 0; k < 0x40; k++) {
        int v = k / 16, e = k % 16;
        int lvl = v < 4 && (PK_ENGINE_MASK >> e & 1) ? ((unsigned)e == engine_of(cur, v) ? LED_ON : LED_DIM) : 0;
        fw_set_led(k, lvl);
    }
}

/* leaving the page: a changed choice goes into the kit and its sidecar */
void pk_vm_page_leave(void)
{
    pressed = 0;
    int bank = FW_U8(SYM_bank_number), kit = *(volatile uint16_t *)(uintptr_t)SYM_current_kit;
    if (kit >= 0 && kit < NKITS && kit_map[kit] != cur) {
        set_kit_map(kit, cur);
        pk_store_save_kit(bank, kit);
    }
}
