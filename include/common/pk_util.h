/* Small helpers for patch code on both cores (included by pk_host.h and pk7_host.h). */
#pragma once
#include <stdint.h>

/* interrupts off around a short critical section:
 *     uint32_t pm = pk_irq_off();  ...  pk_irq_restore(pm); */
static inline uint32_t pk_irq_off(void)
{
    uint32_t primask;
    __asm volatile("mrs %0, primask\n cpsid i" : "=r"(primask) :: "memory");
    return primask;
}

static inline void pk_irq_restore(uint32_t primask)
{
    __asm volatile("msr primask, %0" :: "r"(primask) : "memory");
}

/* copy n bytes (no overlap); when both ends are word aligned, 16 bytes per ldm/stm pair */
static inline void pk_copy(void *dst, const void *src, uint32_t n)
{
    uint8_t *d = dst;
    const uint8_t *s = src;
    if (!(((uintptr_t)d | (uintptr_t)s) & 3)) {
        typedef struct { uint32_t w[4]; } quad_t;
        for (; n >= 16; n -= 16, d += 16, s += 16)
            *(quad_t *)(void *)d = *(const quad_t *)(const void *)s;
        for (; n >= 4; n -= 4, d += 4, s += 4)
            *(uint32_t *)(void *)d = *(const uint32_t *)(const void *)s;
    }
    while (n--)
        *d++ = *s++;
}
