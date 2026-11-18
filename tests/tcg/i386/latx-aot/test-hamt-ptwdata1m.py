#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024-2026 LATS Project Authors
#
# SPDX-License-Identifier: GPL-2.0-only

"""Exercise production HAMT SMC counters and inspect refill emission."""

import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[4]


def function(source, signature):
    start = source.index(signature)
    pos = source.index("{", start)
    depth = 0
    state = "code"
    while pos < len(source):
        char = source[pos]
        next_char = source[pos + 1] if pos + 1 < len(source) else ""
        if state == "code":
            if char == '"':
                state = "string"
            elif char == "'":
                state = "char"
            elif char == "/" and next_char == "/":
                state = "line-comment"
                pos += 1
            elif char == "/" and next_char == "*":
                state = "block-comment"
                pos += 1
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return source[start:pos + 1]
        elif state in ("string", "char"):
            if char == "\\":
                pos += 1
            elif (state == "string" and char == '"') or \
                    (state == "char" and char == "'"):
                state = "code"
        elif state == "line-comment" and char == "\n":
            state = "code"
        elif state == "block-comment" and char == "*" and next_char == "/":
            state = "code"
            pos += 1
        pos += 1
    raise ValueError("unterminated function: " + signature)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ptw-source", type=Path,
                        default=ROOT / "target/i386/hamt/hamt-ptw.c")
    parser.add_argument("--refill-source", type=Path,
                        default=ROOT / "target/i386/latx/optimization/sys-hamt-excp.c")
    args = parser.parse_args()
    source = args.ptw_source.read_text()
    refill = args.refill_source.read_text()
    declarations = source[source.index("uint16_t *ptwdata1m;"):
                          source.index("static void *hamt_new_ptwdata1m(")]
    declarations = declarations.replace(
        "static uint32_t ptwflags_tlb_epoch;\n", ""
    ).replace(
        "static uint32_t ptwflags_seen_epoch[HAMT_CPU_MAX];\n", ""
    )
    harness = r"""
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#define qemu_build_assert(x) assert(x)
#include "qemu/atomic.h"
#include "hamt-ptw.h"
#define _MB_ ((uint64_t)1 << 20)
#define TARGET_PAGE_BITS 12
#define DIV_ROUND_UP(n, d) (((n) + (d) - 1) / (d))
#define HAMT_HOLE_ASSERT(p) ((p) != MAP_FAILED)
#define lsassert(p) assert(p)
#define lsassertm(p, ...) assert(p)
""" + declarations
    for signature in ("static void *hamt_new_ptwdata1m(",
                      "static void *hamt_new_ptwflags(",
                      "static void hamt_ptwflags_refresh_group(",
                      "void hamt_realloc_ptwdata1m(",
                      "void hamt_ptwflags_smc_protect_page(",
                      "void hamt_ptwflags_smc_unprotect_page(",
                      "uint8_t hamt_ptwflags_get_page("):
        harness += function(source, signature) + "\n"
    harness += r"""
int main(void)
{
    const uint64_t page = 4096, region = 1ULL << 20;
    assert(sizeof(*ptwdata1m) >= 2);
    ptwdata1m = hamt_new_ptwdata1m(3);
    ptwflags = hamt_new_ptwflags(4 * 256);
    assert(ptwdata1m_size == 3 * sizeof(*ptwdata1m));
    assert(ptwflags_size == 4 * 256);
    for (unsigned i = 0; i < 3; i++) {
        assert(ptwdata1m[i] == 0);
    }
    for (unsigned i = 0; i < 255; i++) {
        hamt_ptwflags_smc_protect_page(region + i * page);
        assert(hamt_ptwflags_get_page(region + i * page) &
               HAMT_PTWFLAGS_NOWRITE);
        assert(ptwdata1m[1] == i + 1);
    }
    assert(hamt_ptwflags_get_page(region) & HAMT_PTWFLAGS_NO2M);
    hamt_ptwflags_smc_protect_page(region);
    assert(ptwdata1m[1] == 255);
    hamt_ptwflags_smc_protect_page(region + 255 * page);
    assert(ptwdata1m[1] == 256);
    assert(ptwdata1m[0] == 0 && ptwdata1m[2] == 0);
    hamt_ptwflags_smc_protect_page(2 * region);
    assert(ptwdata1m[1] == 256 && ptwdata1m[2] == 1);
    hamt_ptwflags_smc_unprotect_page(region + 255 * page);
    assert(ptwdata1m[1] == 255 && ptwdata1m[2] == 1);
    hamt_ptwflags_smc_unprotect_page(region + 255 * page);
    assert(ptwdata1m[1] == 255);
    hamt_ptwflags_smc_protect_page(region + 255 * page);
    assert(ptwdata1m[1] == 256);
    for (unsigned i = 0; i < 256; i++) {
        hamt_ptwflags_smc_unprotect_page(region + i * page);
        assert(ptwdata1m[1] == 255 - i);
    }
    assert(!(hamt_ptwflags_get_page(region) & HAMT_PTWFLAGS_NO2M));
    hamt_ptwflags_smc_unprotect_page(2 * region);
    assert(ptwdata1m[0] == 0 && ptwdata1m[1] == 0 && ptwdata1m[2] == 0);
    qatomic_or(&ptwflags[page >> 12], HAMT_PTWFLAGS_NOACCESS);
    hamt_ptwflags_smc_protect_page(page);
    hamt_ptwflags_smc_unprotect_page(page);
    assert(hamt_ptwflags_get_page(page) == HAMT_PTWFLAGS_NOACCESS);
    qatomic_and(&ptwflags[page >> 12], ~HAMT_PTWFLAGS_NOACCESS);
    hamt_realloc_ptwdata1m(4 * region);
    assert(ptwdata1m_size == 4 * sizeof(*ptwdata1m));
    for (unsigned i = 0; i < 4; i++) {
        assert(ptwdata1m[i] == 0);
    }
    assert(!munmap(ptwflags, ptwflags_size));
    assert(!munmap(ptwdata1m, ptwdata1m_size));
    puts("PASS: ptwflags and 0 -> 255 -> 256 -> 255 -> 0 SMC counts");
}
"""
    with tempfile.TemporaryDirectory(prefix="hamt-ptw1m-") as directory:
        binary = Path(directory) / "test"
        subprocess.run([*shlex.split(os.environ.get("CC", "cc")),
                        "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-pthread",
                        "-I", str(ROOT / "include"), "-x", "c", "-o",
                        str(binary), "-"], input=harness, text=True, check=True)
        subprocess.run([str(binary)], check=True)

    start = refill.index("/* ptwflags is one byte per 4K GPA.")
    end = refill.index("la_out3(LISA_MASKNEZ", start)
    block = refill[start:end]
    patterns = (
        r"la_out2i\(LISA_SRLI_D,\s*&la_t4,\s*&la_t1,\s*12\)",
        r"la_out2i\(LISA_SRLI_D,\s*&la_t6,\s*&la_t2,\s*12\)",
        r"la_out3\s*\(LISA_LDX_B,\s*&la_t4,\s*&la_a3,\s*&la_t4\)",
        r"la_out3\s*\(LISA_LDX_B,\s*&la_t6,\s*&la_a3,\s*&la_t6\)",
        r"la_out2i\(LISA_ANDI,\s*&la_t4,\s*&la_t4,\s*HAMT_PTWFLAGS_NO2M\)",
        r"la_out2i\(LISA_ANDI,\s*&la_t6,\s*&la_t6,\s*HAMT_PTWFLAGS_NO2M\)",
        r"la_out3\s*\(LISA_OR,\s*&la_a3,\s*&la_t4,\s*&la_t6\)",
        r"la_out2\s*\(LISA_BNEZ,\s*&la_a3,\s*&big_page_do_4k\)",
    )
    position = 0
    for pattern in patterns:
        match = re.search(pattern, block[position:])
        if not match:
            raise AssertionError("missing or reordered refill instruction: " + pattern)
        position += match.end()

    def andi_count(body, flag):
        return len(re.findall(
            rf"LISA_ANDI\s*,[^\n]*{re.escape(flag)}\)", body
        ))

    refill_functions = {
        "2M+4K fallback": function(
            refill, "static void __latxs_gen_hamt_excp_tlbrefill_hamt_ptw2m("
        ),
        "paired 4K": function(
            refill, "static void __latxs_gen_hamt_excp_tlbrefill_hamt_ptw2("
        ),
        "single 4K": function(
            refill, "static void __latxs_gen_hamt_excp_tlbrefill_hamt_ptw("
        ),
    }
    expected_masks = {
        "2M+4K fallback": (4, 4, 2),
        "paired 4K": (2, 2, 0),
        "single 4K": (1, 1, 0),
    }
    for name, body in refill_functions.items():
        actual = (
            andi_count(body, "HAMT_PTWFLAGS_NOACCESS_MASK"),
            andi_count(body, "HAMT_PTWFLAGS_WRITE_MASK"),
            andi_count(body, "HAMT_PTWFLAGS_NO2M"),
        )
        if actual != expected_masks[name]:
            raise AssertionError(f"{name}: ptwflags mask use {actual}")

        write_masks = re.finditer(
            r"LISA_ANDI\s*,\s*&(la_\w+),\s*&la_\w+,\s*"
            r"HAMT_PTWFLAGS_WRITE_MASK\)",
            body,
        )
        for write_mask in write_masks:
            flag_register = write_mask.group(1)
            if not re.search(
                rf"LISA_MASKNEZ\s*,[^\n]*&{flag_register}\)",
                body[write_mask.end():],
            ):
                raise AssertionError(
                    f"{name}: WRITE_MASK result is not applied to a D bit"
                )

    ptw2m = refill_functions["2M+4K fallback"]
    large_precheck_start = ptw2m.index("IR2_OPND big_page_do_4k")
    fallback_label = ptw2m.index("la_label(big_page_do_4k);",
                                 large_precheck_start)
    large_precheck = ptw2m[large_precheck_start:fallback_label]
    if andi_count(large_precheck, "HAMT_PTWFLAGS_NO2M") != 2 or \
            "HAMT_PTWFLAGS_NOACCESS_MASK" in large_precheck or \
            "HAMT_PTWFLAGS_WRITE_MASK" in large_precheck:
        raise AssertionError("2M precheck must depend on NO2M alone")
    if not re.search(r"IR2_OPND\s+big_page_do_4k[\s\S]*"
                     r"LISA_BNEZ\s*,[^\n]+&big_page_do_4k\)",
                     large_precheck):
        raise AssertionError("NO2M does not force the 4K fallback")

    fallback_end = ptw2m.index("la_out1(LISA_B, &ptw_ok);", fallback_label)
    fallback = ptw2m[fallback_label:fallback_end]
    if "HAMT_PTWFLAGS_NO2M" in fallback:
        raise AssertionError("NO2M leaked into the per-4K fallback state")
    if andi_count(fallback, "HAMT_PTWFLAGS_NOACCESS_MASK") != 2 or \
            andi_count(fallback, "HAMT_PTWFLAGS_WRITE_MASK") != 2 or \
            not re.search(r"LISA_BNEZ\s*,[^\n]+&ptw_no\)", fallback):
        raise AssertionError("4K fallback does not enforce permissions")

    for name in ("paired 4K", "single 4K"):
        body = refill_functions[name]
        first_noaccess = body.index("HAMT_PTWFLAGS_NOACCESS_MASK")
        if not re.search(r"LISA_(?:BNEZ|BEQZ)[^\n]+&ptw_no\)",
                         body[first_noaccess:]):
            raise AssertionError(f"{name}: NOACCESS does not invalidate the ELO")

    plv_signature = "static void set_hamt_tlbr_plv("
    plv_start = refill.index(plv_signature, refill.index(plv_signature) + 1)
    plv_body = function(refill[plv_start:], plv_signature)
    plv_patterns = (
        r"LISA_LD_WU\s*,[^\n]+tmp0[^\n]*",
        r"hamt_tlbr_user_mask\[0\]",
        r"LISA_ORI\s*,[^\n]+0x3 << 2\)",
        r"LISA_MASKEQZ\s*,[^\n]+tmp1[^\n]+tmp0\)",
        r"LISA_OR\s*,[^\n]+elo0[^\n]+tmp1\)",
        r"LISA_OR\s*,[^\n]+elo1[^\n]+tmp1\)",
    )
    for pattern in plv_patterns:
        if not re.search(pattern, plv_body):
            raise AssertionError("invalid PLV publication: " + pattern)

    legacy_norefill = "HAMT_PTWFLAGS_" + "NOREFILL"
    if legacy_norefill in refill or any(
            token in refill for token in ("ptwdata", "ptw4k")):
        raise AssertionError("refill still uses legacy PTW state")
    print("PASS: refill uses unified ptwflags for 2M, 4K, access and write state")

    plv_paths = {
        "__latxs_gen_hamt_excp_tlbrefill_dbt": (1, 0),
        "__latxs_gen_hamt_excp_tlbrefill_hamt_zero": (1, 0),
        "__latxs_gen_hamt_excp_tlbrefill_hamt_ptw2m": (4, 3),
        "__latxs_gen_hamt_excp_tlbrefill_hamt_ptw2": (2, 1),
        "__latxs_gen_hamt_excp_tlbrefill_hamt_ptw": (2, 1),
    }
    for name, (fills, plv_fills) in plv_paths.items():
        body = function(refill, "static void " + name + "(")
        actual_fills = body.count("0x06483400")
        actual_plv_fills = body.count("set_hamt_tlbr_plv(")
        if (actual_fills, actual_plv_fills) != (fills, plv_fills):
            raise AssertionError(
                f"{name}: tlbfill/PLV counts {(actual_fills, actual_plv_fills)}"
                f" != {(fills, plv_fills)}"
            )
    total_fills = sum(fills for fills, _ in plv_paths.values())

    record_sig = "static void record_hamt_tlbr_user_masks("
    record_start = refill.index(record_sig, refill.index(record_sig) + 1)
    record = function(refill[record_start:], record_sig)
    if record.count("PG_USER_MASK") != 2 or "PRMD" in record:
        raise AssertionError("refill must record both PTE U/S masks")
    for name, expected in (
        ("__latxs_gen_hamt_excp_tlbrefill_hamt_ptw2m", (1, 1)),
        ("__latxs_gen_hamt_excp_tlbrefill_hamt_ptw2", (1, 1)),
        ("__latxs_gen_hamt_excp_tlbrefill_hamt_ptw", (1, 0)),
    ):
        body = function(refill, "static void " + name + "(")
        actual = (body.count("record_hamt_tlbr_user_masks(&la_t6, &la_t6, &la_t4)"),
                  body.count("record_hamt_tlbr_user_masks(&la_a0, &la_a1, &la_t3)"))
        if actual != expected:
            raise AssertionError(f"{name}: wrong PTE U/S sources: {actual}")
    print("PASS: refill PLV follows guest PTE U/S state")

    if refill.count("0x06483400") != total_fills:
        raise AssertionError("unclassified tlbfill emission site")
    print("PASS: every PLV-producing guest tlbrefill fills PTE-derived PLV")

    ptw_body = function(source, "static bool hamt_do_ptw(")
    guest_check = ptw_body.index(
        "if (is_user && !(ptep & PG_USER_MASK))"
    )
    plv_select = ptw_body.index("if (hamt_enable_plv())")
    if guest_check > plv_select:
        raise AssertionError("guest user/supervisor check depends on PLV mode")
    print("PASS: guest user/supervisor page faults are checked before PLV setup")

    static_codes = (ROOT / "target/i386/latx/translator/sys-static-codes.c").read_text()
    prologue = function(static_codes, "static int gen_latxs_sc_prologue(")
    enter_plv0 = prologue.index("latxs_tr_dmw_in_plv0_break();")
    for operation in ("latxs_tr_dmw_in_fix_asid_tmp(",
                      "latxs_tr_dmw_in_pg_tmp(", "latxs_tr_dmw_in_plv_env_tmp("):
        if enter_plv0 > prologue.index(operation):
            raise AssertionError("prologue changes CSR before switching to PLV0")
    print("PASS: prologue enters PLV0 before privileged CSR operations")


if __name__ == "__main__":
    main()
