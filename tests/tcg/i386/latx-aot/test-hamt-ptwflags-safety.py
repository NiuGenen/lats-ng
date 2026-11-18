#!/usr/bin/env python3
"""Stress ptwflags transitions and validate refill invalidation ordering."""

import argparse
from pathlib import Path
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


def build_harness(source):
    declarations = source[source.index("uint16_t *ptwdata1m;"):
                          source.index("static void *hamt_new_ptwdata1m(")]
    declarations = declarations.replace(
        "static uint32_t ptwflags_tlb_epoch;\n", ""
    )
    declarations = declarations.replace(
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
#define g_assert(p) assert(p)
static int test_hamt_enabled = 1;
static int test_hamt_running = 1;
static int test_flushes;
static int hamt_enabled(void) { return test_hamt_enabled; }
static int hamt_is_running(void) { return test_hamt_running; }
static int hamt_no_vga_dirty(void) { return 0; }
void hamt_ptwflags_invalidate_all(void)
{
    qatomic_inc(&test_flushes);
}
""" + declarations
    for signature in (
        "static void *hamt_new_ptwdata1m(",
        "static void *hamt_new_ptwflags(",
        "static void hamt_ptwflags_flush_tlb(",
        "static inline bool hamt_ptwflags_update_range(",
        "static void hamt_ptwflags_refresh_group(",
        "static void hamt_ptwflags_refresh_range(",
        "void hamt_ptwflags_set_mmio(",
        "void hamt_ptwflags_vga_protect(",
        "void hamt_ptwflags_smc_protect_page(",
        "void hamt_ptwflags_smc_unprotect_page(",
        "uint8_t hamt_ptwflags_get_page(",
    ):
        harness += function(source, signature) + "\n"
    return harness


def run_host_tests(source, cputlb, compiler):
    harness = build_harness(source)
    harness += r"""
#define GROUPS 6
#define THREADS 12
#define ITERATIONS 20000
#define MMIO_ITERATIONS 2000

typedef struct {
    uint64_t group;
    unsigned index;
} worker_arg_t;

static volatile int race_error;

static void *toggle_worker(void *opaque)
{
    const worker_arg_t *arg = opaque;

    for (unsigned i = 0; i < ITERATIONS; i++) {
        uint64_t page = arg->group + ((i + arg->index) & 7) * PAGE;

        if ((i + arg->index) & 1) {
            hamt_ptwflags_smc_protect_page(page);
        } else {
            hamt_ptwflags_smc_unprotect_page(page);
        }
        if (!((i + arg->index) & 3)) {
            hamt_ptwflags_smc_protect_page(page);
            hamt_ptwflags_smc_unprotect_page(page);
        }
        if (qatomic_read(&ptwdata1m[arg->group >> 20]) > 8) {
            qatomic_set(&race_error, 1);
        }
    }
    return NULL;
}

static void *mmio_worker(void *opaque)
{
    const worker_arg_t *arg = opaque;

    for (unsigned i = 0; i < MMIO_ITERATIONS; i++) {
        hamt_ptwflags_set_mmio(arg->group + PAGE, PAGE);
    }
    return NULL;
}

int main(void)
{
    const uint64_t group2 = 2ULL << 20;
    const uint64_t group3 = 3ULL << 20;
    pthread_t threads[THREADS];
    worker_arg_t args[THREADS];
    int initial_flushes;

    ptwflags_size = GROUPS * 256;
    ptwflags = hamt_new_ptwflags(ptwflags_size);
    ptwdata1m_size = GROUPS * sizeof(*ptwdata1m);
    ptwdata1m = hamt_new_ptwdata1m(GROUPS);

    hamt_ptwflags_set_mmio(1ULL << 20, PAGE);
    assert(test_flushes == 1);
    assert(hamt_ptwflags_get_page(1ULL << 20) &
           (HAMT_PTWFLAGS_NOACCESS | HAMT_PTWFLAGS_NO2M));
    hamt_ptwflags_set_mmio(1ULL << 20, PAGE);
    assert(test_flushes == 1);
    hamt_ptwflags_vga_protect((4ULL << 20) + PAGE, PAGE);
    assert(test_flushes == 2);
    assert(hamt_ptwflags_get_page((4ULL << 20) + PAGE) ==
           HAMT_PTWFLAGS_NOACCESS);

    for (unsigned i = 0; i < 8; i++) {
        hamt_ptwflags_smc_protect_page(group2 + i * PAGE);
    }
    for (unsigned i = 0; i < THREADS; i++) {
        args[i].group = group2;
        args[i].index = i;
        assert(!pthread_create(&threads[i], NULL, toggle_worker, &args[i]));
    }
    for (unsigned i = 0; i < THREADS; i++) {
        assert(!pthread_join(threads[i], NULL));
    }
    for (unsigned i = 0; i < 8; i++) {
        hamt_ptwflags_smc_unprotect_page(group2 + i * PAGE);
    }
    assert(!race_error);
    assert(ptwdata1m[2] == 0);
    assert(hamt_ptwflags_get_page(group2) == 0);

    for (unsigned i = 0; i < 8; i++) {
        hamt_ptwflags_smc_protect_page(group3 + i * PAGE);
    }
    initial_flushes = qatomic_read(&test_flushes);
    for (unsigned i = 0; i < THREADS - 1; i++) {
        args[i].group = group3;
        args[i].index = i;
        assert(!pthread_create(&threads[i], NULL, toggle_worker, &args[i]));
    }
    args[THREADS - 1].group = group3;
    args[THREADS - 1].index = THREADS - 1;
    assert(!pthread_create(&threads[THREADS - 1], NULL, mmio_worker,
                           &args[THREADS - 1]));
    for (unsigned i = 0; i < THREADS; i++) {
        assert(!pthread_join(threads[i], NULL));
    }
    for (unsigned i = 0; i < 8; i++) {
        hamt_ptwflags_smc_unprotect_page(group3 + i * PAGE);
    }
    assert(qatomic_read(&test_flushes) == initial_flushes + 1);
    assert(ptwdata1m[3] == 0);
    assert(hamt_ptwflags_get_page(group3 + PAGE) ==
           HAMT_PTWFLAGS_NOACCESS);
    assert(hamt_ptwflags_get_page(group3) &
           (HAMT_PTWFLAGS_NOACCESS | HAMT_PTWFLAGS_NO2M));

    assert(!munmap(ptwflags, ptwflags_size));
    assert(!munmap(ptwdata1m, ptwdata1m_size));
    puts("PASS: concurrent ptwflags transitions and MMIO TLB invalidation");
    return 0;
}
"""
    with tempfile.TemporaryDirectory(prefix="hamt-ptwflags-safety-") as directory:
        binary = Path(directory) / "test"
        subprocess.run(
            [*shlex.split(compiler), "-std=gnu11", "-O2", "-Wall", "-Wextra",
             "-Werror", "-pthread", "-I", str(ROOT / "include"), "-x", "c",
             "-o", str(binary), "-"],
            input=harness, text=True, check=True,
        )
        subprocess.run([str(binary)], check=True)

    set_mmio_body = function(source, "void hamt_ptwflags_set_mmio(")
    protect_body = function(source, "void hamt_ptwflags_smc_protect_page(")
    unprotect_body = function(source, "void hamt_ptwflags_smc_unprotect_page(")
    flush_body = function(source, "static void hamt_ptwflags_flush_tlb(")
    invalidate_body = function(source, "void hamt_ptwflags_invalidate_all(")
    sync_body = function(source, "void hamt_ptwflags_sync_tlb(")
    for body, operation in ((protect_body, "fetch_or"),
                            (unprotect_body, "fetch_and")):
        lock = body.index("pthread_mutex_lock(&ptwflags_lock)")
        transition = body.index(operation)
        unlock = body.index("pthread_mutex_unlock(&ptwflags_lock)")
        if not lock < transition < unlock:
            raise AssertionError("SMC transition is not serialized")
    update = set_mmio_body.index("hamt_ptwflags_update_range")
    refresh = set_mmio_body.index("hamt_ptwflags_refresh_range")
    unlock = set_mmio_body.index("pthread_mutex_unlock(&ptwflags_lock)")
    flush = set_mmio_body.index("hamt_ptwflags_flush_tlb()")
    if not update < refresh < unlock < flush:
        raise AssertionError("MMIO state is not published before TLB invalidation")
    if "hamt_ptwflags_invalidate_all()" not in flush_body:
        raise AssertionError("ptwflags invalidation does not synchronize HAMT TLBs")
    if "qatomic_inc(&ptwflags_tlb_epoch)" not in invalidate_body or \
            "CPU_FOREACH(cpu)" not in invalidate_body:
        raise AssertionError("ptwflags invalidation does not kick every vCPU")
    if "hamt_flush_tlb_cpu(cpu)" not in sync_body or \
            "ptwflags_seen_epoch[cpuid]" not in sync_body:
        raise AssertionError("deferred ptwflags TLB flush is not epoch based")

    tlb_body = function(cputlb, "void tlb_protect_code(")
    tag = tlb_body.index("hamt_ptwflags_smc_protect_page")
    flush = tlb_body.index("hamt_protect_code", tag)
    if not tag < flush:
        raise AssertionError("SMC permission published after code TLB invalidation")
    print("PASS: ptwflags state publication precedes all TLB invalidation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ptw-source", type=Path,
                        default=ROOT / "target/i386/hamt/hamt-ptw.c")
    parser.add_argument("--cputlb-source", type=Path,
                        default=ROOT / "accel/tcg/cputlb.c")
    args = parser.parse_args()
    run_host_tests(args.ptw_source.read_text(), args.cputlb_source.read_text(),
                   "cc")


if __name__ == "__main__":
    main()
