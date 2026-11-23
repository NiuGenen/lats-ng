/*
 * SPDX-FileCopyrightText: 2024-2026 LATS Project Authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "common.h"
#include "cpu.h"
#include "lsenv.h"
#include "reg-alloc.h"
#include "latx-options.h"
#include "translate.h"
#include "sys-excp.h"
#include <string.h>

#include "latx-sys-hamt-dmw.h"

void latxs_tr_dmw_in_fix_mem(IR2_OPND *mem)
{
    if (hamt_mode_dmw()) {
        latxs_append_ir2_opnd2i(LISA_LU52I_D, mem, mem, 0x900);
    }
}

void latxs_tr_dmw_out_fix_mem(IR2_OPND *mem)
{
    if (hamt_mode_dmw()) {
        latxs_append_ir2_opnd2i(LISA_LU52I_D, mem, mem, 0x000);
    }
}

/* Legacy DMW mode switches ASID between translator and guest mappings. */
static void enter_guest_asid(IR2_OPND *tmp, IR2_OPND *env)
{
    if (hamt_mode_dmw() && !hamt_dmw_mode_da() && !hamt_disable_asid()) {
        IR2_OPND *zero = &latxs_zero_ir2_opnd;
        if (option_pcid_asid) {
            QEMU_BUILD_BUG_ON(offsetof(CPUX86State, hamt_guest_asid) >= 2048);
            latxs_append_ir2_opnd2i(LISA_LD_HU, tmp, env,
                                    offsetof(CPUX86State, hamt_guest_asid));
        } else {
            latxs_append_ir2_opnd2i(LISA_ORI, tmp, zero, 0xf);
        }
        latxs_append_ir2_opnd2(LISA_CSRWR, &la_csr_asid, tmp);
    }
}

void latxs_tr_dmw_in_fix_asid(IR2_OPND *tmp)
{
    enter_guest_asid(tmp, &latxs_env_ir2_opnd);
}

void latxs_tr_dmw_out_fix_asid(IR2_OPND *tmp)
{
    if (hamt_mode_dmw() && !hamt_dmw_mode_da() && !hamt_disable_asid()) {
        IR2_OPND *zero = &latxs_zero_ir2_opnd;
        latxs_append_ir2_opnd2(LISA_CSRWR, &la_csr_asid, zero);
    }
}

void latxs_tr_dmw_in_fix_asid_tmp(IR2_OPND *env)
{
    if (hamt_mode_dmw() && !hamt_dmw_mode_da() && !hamt_disable_asid()) {
        IR2_OPND tmp = latxs_ra_alloc_itemp();
        enter_guest_asid(&tmp, env);
        latxs_ra_free_temp(&tmp);
    }
}

void latxs_tr_dmw_out_fix_asid_tmp(void)
{
    if (hamt_mode_dmw() && !hamt_dmw_mode_da() && !hamt_disable_asid()) {
        IR2_OPND tmp = latxs_ra_alloc_itemp();
        latxs_tr_dmw_out_fix_asid(&tmp);
        latxs_ra_free_temp(&tmp);
    }
}

void latxs_tr_dmw_in_pg(IR2_OPND *tmp0, IR2_OPND *tmp1)
{
    if (hamt_dmw_mode_da()) {
        la_out2i(LISA_ORI, tmp0, &la_zero, (0 << 3) | (1 << 4));
        la_out2i(LISA_ORI, tmp1, &la_zero, (1 << 3) | (1 << 4));
        la_out3(LISA_CSRXCHG, &la_csr_crmd, tmp0, tmp1);
        la_comment("HAMT: enter PG mode");
    }
}

void latxs_tr_dmw_in_da(IR2_OPND *tmp0, IR2_OPND *tmp1)
{
    if (hamt_dmw_mode_da()) {
        la_out2i(LISA_ORI, tmp0, &la_zero, (1 << 3) | (0 << 4));
        la_out2i(LISA_ORI, tmp1, &la_zero, (1 << 3) | (1 << 4));
        la_out3(LISA_CSRXCHG, &la_csr_crmd, tmp0, tmp1);
        la_comment("HAMT: enter DA mode");
    }
}

void latxs_tr_dmw_in_pg_tmp(void)
{
    if (hamt_dmw_mode_da()) {
        IR2_OPND t0 = latxs_ra_alloc_itemp();
        IR2_OPND t1 = latxs_ra_alloc_itemp();
        latxs_tr_dmw_in_pg(&t0, &t1);
        latxs_ra_free_temp(&t0);
        latxs_ra_free_temp(&t1);
    }
}

void latxs_tr_dmw_in_da_tmp(void)
{
    if (hamt_dmw_mode_da()) {
        IR2_OPND t0 = latxs_ra_alloc_itemp();
        IR2_OPND t1 = latxs_ra_alloc_itemp();
        latxs_tr_dmw_in_da(&t0, &t1);
        latxs_ra_free_temp(&t0);
        latxs_ra_free_temp(&t1);
    }
}
