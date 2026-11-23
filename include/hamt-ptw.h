/*
 * SPDX-FileCopyrightText: 2024-2026 LATS Project Authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef _HATM_PTW_H_
#define _HATM_PTW_H_

/* Final HAMT direct-access permissions for one 4K GPA. */
#define HAMT_PTWFLAGS_NOWRITE       (1U << 0)
#define HAMT_PTWFLAGS_NOACCESS      (1U << 1)
#define HAMT_PTWFLAGS_NOACCESS_MASK (0x7eU)
#define HAMT_PTWFLAGS_WRITE_MASK    (0x7fU)
/* Set on the first page of a 1M group when a 1M mapping is unsafe. */
#define HAMT_PTWFLAGS_NO2M          (1U << 7)

void *hamt_get_ptwdata1m(void);
void *hamt_get_ptwflags(void);
uint64_t hamt_get_ptwflags_size(void);
void hamt_ptwflags_set_mmio(uint64_t base, uint64_t size);
void hamt_ptwflags_vga_protect(uint64_t base, uint64_t size);
void hamt_ptwflags_smc_protect_page(uint64_t page);
void hamt_ptwflags_smc_unprotect_page(uint64_t page);
void hamt_ptwflags_invalidate_all(void);

struct CPUState;
void hamt_ptwflags_sync_tlb(struct CPUState *cpu);
void hamt_smc_resume_flush(struct CPUState *cpu);

bool hamt_ptwflags_smc_page_is_protected(uint64_t page);
bool hamt_ptwflags_smc_range_is_protected(uint64_t base, uint64_t size);

uint8_t hamt_ptwflags_get_page(uint64_t page);

void *hamt_get_ptwrcd(int cpuid);
void hamt_set_ptwrcd(int cpuid, uint64_t gpa);
void hamt_clr_ptwrcd(int cpuid);

enum {
    HAMT_PTW_ERROR_NONE,
    HAMT_PTW_ERROR_DISABLE,
    HAMT_PTW_ERROR_PF,
    HAMT_PTW_ERROR_NOTRAM,
    HAMT_PTW_ERROR_SMC,
    HAMT_PTW_ERROR_VGA,
    HAMT_PTW_ERROR_MMIO,
};

typedef struct {
    int error;
    int error_code;
    uint64_t paddr;
} hamt_ptw_error_t;

#endif
