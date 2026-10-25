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

#define FW_JSON_BOOL        0x80u
#define FW_JSON_U8          0x81u   /* note: values are truncated to 8 bits */
#define FW_JSON_ENUM        0x86u
#define FW_JSON_OBJECT      0x87u

#define fw_load_samples     FW_CALL(SYM_load_samples, void (*)(int bank))
#define fw_json_load        FW_CALL(SYM_json_load, int (*)(const char *path, const fw_json_schema_t *, void *))
#define fw_file_exists      FW_CALL(SYM_file_exists, int (*)(const char *path))
#define fw_snprintf         FW_CALL(SYM_snprintf, int (*)(char *, unsigned, const char *, ...))
#define fw_ipc_send         FW_CALL(SYM_ipc_send, int (*)(int stream, const void *, int len, int type))

#define FW_IPC_CONFIG       3       /* stream for M4 -> M7 config messages */
