#!/usr/bin/env python3
"""Exercise the production HAMT ptwflags state machine."""

import argparse
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[4]
PAGE = 4096
GROUP = 1 << 20


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


def build_harness(source):
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
#define TARGET_PAGE_SIZE (1U << TARGET_PAGE_BITS)
#define PAGE TARGET_PAGE_SIZE
#define TARGET_PAGE_ALIGN(x) (((x) + TARGET_PAGE_SIZE - 1) & \
                              ~(TARGET_PAGE_SIZE - 1))
#define DIV_ROUND_UP(n, d) (((n) + (d) - 1) / (d))
#define HAMT_HOLE_ASSERT(p) ((p) != MAP_FAILED)
#define lsassert(p) assert(p)
#define lsassertm(p, ...) assert(p)
static void hamt_ptwflags_flush_tlb(void) {}
""" + declarations
    for signature in (
        "static void *hamt_new_ptwdata1m(",
        "static void *hamt_new_ptwflags(",
        "static inline bool hamt_ptwflags_update_range(",
        "static void hamt_ptwflags_refresh_group(",
        "static void hamt_ptwflags_refresh_range(",
        "void hamt_ptwflags_set_mmio(",
        "void hamt_ptwflags_smc_protect_page(",
        "void hamt_ptwflags_smc_unprotect_page(",
        "uint8_t hamt_ptwflags_get_page(",
        "bool hamt_ptwflags_smc_page_is_protected(",
        "bool hamt_ptwflags_smc_range_is_protected(",
    ):
        harness += function(source, signature) + "\n"
    return harness


def run_host_tests(source, compiler):
    harness = build_harness(source)
    harness += r"""
static uint8_t group_flags(uint64_t group)
{
    return hamt_ptwflags_get_page(group * (1ULL << 20));
}

static uint8_t page_flags(uint64_t page)
{
    return hamt_ptwflags_get_page(page) & ~HAMT_PTWFLAGS_NO2M;
}

int main(void)
{
    const uint64_t groups = 5;
    uint64_t group1 = 1ULL << 20;
    uint64_t group2 = 2ULL << 20;
    uint8_t flags;

    ptwflags_size = groups * 256;
    ptwflags = hamt_new_ptwflags(ptwflags_size);
    ptwdata1m_size = groups * sizeof(*ptwdata1m);
    ptwdata1m = hamt_new_ptwdata1m(groups);

    assert(HAMT_PTWFLAGS_WRITE_MASK == 0x7f);
    assert(HAMT_PTWFLAGS_NOACCESS_MASK == 0x7e);
    assert(HAMT_PTWFLAGS_NO2M == 0x80);

    hamt_ptwflags_smc_protect_page(group1);
    assert(page_flags(group1) == HAMT_PTWFLAGS_NOWRITE);
    assert(ptwdata1m[1] == 1);
    assert(group_flags(1) & HAMT_PTWFLAGS_NO2M);
    hamt_ptwflags_smc_protect_page(group1);
    assert(ptwdata1m[1] == 1);

    qatomic_or(&ptwflags[group1 >> 12], HAMT_PTWFLAGS_NOACCESS);
    hamt_ptwflags_smc_unprotect_page(group1);
    assert(page_flags(group1) == HAMT_PTWFLAGS_NOACCESS);
    assert(ptwdata1m[1] == 0);
    assert(group_flags(1) & HAMT_PTWFLAGS_NO2M);
    qatomic_and(&ptwflags[group1 >> 12], ~HAMT_PTWFLAGS_NOACCESS);
    hamt_ptwflags_refresh_group(1);
    assert(group_flags(1) == 0);

    qatomic_or(&ptwflags[(group1 + PAGE) >> 12], 1U << 2);
    hamt_ptwflags_refresh_group(1);
    flags = hamt_ptwflags_get_page(group1 + PAGE);
    assert(flags & HAMT_PTWFLAGS_NOACCESS_MASK);
    assert(group_flags(1) & HAMT_PTWFLAGS_NO2M);
    qatomic_and(&ptwflags[(group1 + PAGE) >> 12], ~(1U << 2));
    hamt_ptwflags_refresh_group(1);
    assert(!(group_flags(1) & HAMT_PTWFLAGS_NO2M));

    qatomic_or(&ptwflags[group1 >> 12], HAMT_PTWFLAGS_NO2M);
    hamt_ptwflags_refresh_group(1);
    assert(!(group_flags(1) & HAMT_PTWFLAGS_NO2M));

    hamt_ptwflags_smc_protect_page(group1 + 255 * PAGE);
    assert(ptwdata1m[1] == 1);
    assert(group_flags(1) & HAMT_PTWFLAGS_NO2M);
    assert(!(group_flags(2) & HAMT_PTWFLAGS_NO2M));
    hamt_ptwflags_smc_unprotect_page(group1 + 255 * PAGE);
    assert(group_flags(1) == 0);

    for (unsigned i = 0; i < 255; i++) {
        hamt_ptwflags_smc_protect_page(group2 + i * PAGE);
    }
    assert(ptwdata1m[2] == 255);
    hamt_ptwflags_smc_protect_page(group2 + 255 * PAGE);
    assert(ptwdata1m[2] == 256);
    hamt_ptwflags_smc_protect_page(group2);
    assert(ptwdata1m[2] == 256);
    for (unsigned i = 0; i < 256; i++) {
        hamt_ptwflags_smc_unprotect_page(group2 + i * PAGE);
    }
    assert(ptwdata1m[2] == 0);
    assert(group_flags(2) == 0);

    hamt_ptwflags_set_mmio(group2 - PAGE, 2 * PAGE);
    assert(page_flags(group2 - PAGE) == HAMT_PTWFLAGS_NOACCESS);
    assert(page_flags(group2) == HAMT_PTWFLAGS_NOACCESS);
    assert(group_flags(1) & HAMT_PTWFLAGS_NO2M);
    assert(group_flags(2) & HAMT_PTWFLAGS_NO2M);

    assert(hamt_ptwflags_smc_page_is_protected(group1) == false);
    assert(hamt_ptwflags_smc_range_is_protected(group1, 256 * PAGE) == false);

    assert(!munmap(ptwflags, ptwflags_size));
    assert(!munmap(ptwdata1m, ptwdata1m_size));
    puts("PASS: ptwflags masks, SMC counts, overlapping reasons and NO2M groups");
    return 0;
}
"""
    with tempfile.TemporaryDirectory(prefix="hamt-ptwflags-") as directory:
        binary = Path(directory) / "test"
        subprocess.run([*shlex.split(compiler), "-std=gnu11", "-O2", "-pthread",
                        "-Wall", "-Wextra", "-Werror", "-I",
                        str(ROOT / "include"), "-x", "c", "-o", str(binary), "-"],
                       input=harness, text=True, check=True)
        subprocess.run([str(binary)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ptw-source", type=Path,
                        default=ROOT / "target/i386/hamt/hamt-ptw.c")
    args = parser.parse_args()
    run_host_tests(args.ptw_source.read_text(), "cc")


if __name__ == "__main__":
    main()
