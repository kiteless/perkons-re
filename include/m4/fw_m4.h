/* Perkons M4 firmware interface for patch code.
 * Every address comes from the generated fw_syms.h (symbols/<version>-m4.json). */
#pragma once
#include <stdint.h>
#include "fw_syms.h"

#define FW_CALL(sym, type)  ((type)((uintptr_t)(sym) | 1u))

/* firmware's schema-driven JSON loader; see symbols/v1.3.0-m4.json "_json_schema_format" */
typedef struct {
    const char *key;
    uint32_t offset;            /* byte offset in the target struct */
    uint32_t type;              /* FW_JSON_* */
    const void *enum_table;
    const void *nested;
} fw_json_entry_t;

typedef struct {
    const fw_json_entry_t *entries;
    uint32_t count;
} fw_json_schema_t;

/* FW_JSON_ENUM entries: enum_table points at one of these. The loader stores (u8) the
 * index of the name that matches the JSON string exactly; any other value, including
 * a number, stores 0. Keep index 0 for "unknown". */
typedef struct {
    const char *const *names;
    uint32_t count;
} fw_json_enum_t;

#define FW_JSON_BOOL        0x80u
#define FW_JSON_U8          0x81u   /* note: values are truncated to 8 bits */
#define FW_JSON_ENUM        0x86u
#define FW_JSON_OBJECT      0x87u

#define fw_load_samples     FW_CALL(SYM_load_samples, void (*)(int bank))
#define fw_json_load        FW_CALL(SYM_json_load, int (*)(const char *path, const fw_json_schema_t *, void *))
#define fw_json_save        FW_CALL(SYM_json_save, int (*)(const char *path, const fw_json_schema_t *, const void *))
#define fw_device_json_save FW_CALL(SYM_device_json_save, void (*)(void))   /* system/device.json */
#define fw_file_exists      FW_CALL(SYM_file_exists, int (*)(const char *path))
#define fw_snprintf         FW_CALL(SYM_snprintf, int (*)(char *, unsigned, const char *, ...))
#define fw_ipc_send         FW_CALL(SYM_ipc_send, int (*)(int stream, const void *, int len, int type))

#define FW_IPC_CONFIG       3       /* stream for M4 -> M7 config messages */

/* --- FX (BBD) path; see docs/architecture.md "FX / BBD" ---------------------------- */
typedef void (*fw_fx_proc_t)(const int16_t *in, int16_t *out);   /* 16 stereo frames, L used */
#define fw_fx_bbd_process   FW_CALL(SYM_fx_bbd_process, fw_fx_proc_t)
#define fw_fx_lfo_led_pwm   FW_CALL(SYM_fx_lfo_led_pwm, void (*)(uint32_t pwm))   /* LFO LED, 0..0xffff */
#define fw_gpio_read        FW_CALL(SYM_hal_gpio_read, int (*)(void *port, uint16_t pin))
#define fw_set_led          FW_CALL(SYM_set_led, void (*)(int key, int level))
#define fw_cfg_event        FW_CALL(SYM_cfg_event, int (*)(const uint8_t *evt))
#define fw_cfg_render       FW_CALL(SYM_cfg_render, void (*)(void *, void *, void *, void *))
#define fw_config_files_init FW_CALL(SYM_config_files_init, void (*)(void))

#define FW_F32(addr)        (*(volatile float *)(uintptr_t)(addr))
#define FW_U8(addr)         (*(volatile uint8_t *)(uintptr_t)(addr))
#define FW_U32(addr)        (*(volatile uint32_t *)(uintptr_t)(addr))

/* effective FX controls computed by stock fx_update (after kit recall / pot catch) */
#define FW_FX_TIME          FW_F32(SYM_fx_time)                            /* 0..1 */
#define FW_FX_FEEDBACK      FW_F32(SYM_fx_feedback)                        /* 0..1.02, slewed */
#define FW_FX_LFO_RATE      FW_F32(SYM_fx_lfo_state + OFF_fx_lfo_rate)     /* (0.1+pot*20)/3000 */
#define FW_FX_LFO_DEPTH     FW_F32(SYM_fx_lfo_state + OFF_fx_lfo_depth)    /* pot*0.3 */
#define FW_FX_SWITCH        FW_U8(SYM_fx_switch_eff)                       /* 1 = SHORT */
#define FW_BBD_STAGES       FW_U32(SYM_fx_bbd_state + OFF_fx_bbd_stages)
#define FW_BBD_TICKS        FW_F32(SYM_fx_bbd_state + OFF_fx_bbd_ticks)    /* BBD clock ticks per sample */
#define FW_BBD_LINE         ((float *)(uintptr_t)SYM_fx_bbd_line)          /* 16 KB */

/* zero the BBD's signal state (input history, filter states, last output), leaving its
 * settings; with the line cleared too, the delay restarts silent (as after fx_init) */
static inline void fw_fx_bbd_clear_state(void)
{
    for (uint32_t o = OFF_fx_bbd_history; o < OFF_fx_bbd_history + 0x20; o += 4)
        FW_F32(SYM_fx_bbd_state + o) = 0.0f;
    FW_F32(SYM_fx_bbd_state + OFF_fx_bbd_state_a) = 0.0f;
    FW_F32(SYM_fx_bbd_state + OFF_fx_bbd_state_b) = 0.0f;
    FW_F32(SYM_fx_bbd_state + OFF_fx_bbd_last_out) = 0.0f;
}
#define FW_SYNC_ON          FW_U8(SYM_device_config + OFF_device_config_bbd_sync)
#define FW_CLOCK_BPM        FW_F32(SYM_clock_state + OFF_clock_bpm)
#define FW_SYNC_TABLE       ((const float *)(uintptr_t)SYM_fx_sync_table)  /* 17 beat multipliers */
#define FW_CFG_DIRTY        FW_U8(SYM_cfg_dirty)
