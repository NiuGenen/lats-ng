/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>

#include "hamt-smc-vcpu-bitmap.h"

enum { THREADS = 16, PAGES = 130, ROUNDS = 50000 };
static HamtSmcVcpuBitmap bitmap;
static pthread_barrier_t start, finish;
static unsigned char flags;
static bool fill_saw_protection;
static bool protector_saw_mark;

static void *fill_racer(void *unused)
{
    (void)unused;
    for (int i = 0; i < ROUNDS; i++) {
        pthread_barrier_wait(&start);
        assert(hamt_smc_vcpu_bitmap_mark(&bitmap, 0));
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        fill_saw_protection = __atomic_load_n(&flags, __ATOMIC_RELAXED);
        pthread_barrier_wait(&finish);
    }
    return NULL;
}

static void *protect_racer(void *unused)
{
    (void)unused;
    for (int i = 0; i < ROUNDS; i++) {
        pthread_barrier_wait(&start);
        __atomic_store_n(&flags, 1, __ATOMIC_RELAXED);
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        protector_saw_mark = hamt_smc_vcpu_bitmap_test(&bitmap, 0);
        pthread_barrier_wait(&finish);
    }
    return NULL;
}

static void test_publication(void)
{
    pthread_t fill, protect;

    assert(!pthread_barrier_init(&start, NULL, 3));
    assert(!pthread_barrier_init(&finish, NULL, 3));
    assert(!pthread_create(&fill, NULL, fill_racer, NULL));
    assert(!pthread_create(&protect, NULL, protect_racer, NULL));
    for (int i = 0; i < ROUNDS; i++) {
        /* Workers are parked at the start barrier, so clearing is quiescent. */
        hamt_smc_vcpu_bitmap_clear(&bitmap);
        __atomic_store_n(&flags, 0, __ATOMIC_RELAXED);
        pthread_barrier_wait(&start);
        pthread_barrier_wait(&finish);
        assert(fill_saw_protection || protector_saw_mark);
    }
    assert(!pthread_join(fill, NULL));
    assert(!pthread_join(protect, NULL));
    assert(!pthread_barrier_destroy(&start));
    assert(!pthread_barrier_destroy(&finish));
}

static void *mark_bit(void *arg)
{
    uintptr_t page = (uintptr_t)arg;

    for (int i = 0; i < 10000; i++) {
        assert(hamt_smc_vcpu_bitmap_mark(&bitmap, page << 12));
    }
    return NULL;
}

/*
 * A synchronous IPI may clear a pre-fill mark while the fill is interrupted.
 * A post-fill mark plus permission recheck makes this interleaving visible to
 * a subsequent protector, or removes the stale writable mapping locally.
 * This is a protocol model, not a test of the production exception handler.
 */
static void test_interrupted_fill(void)
{
    HamtSmcVcpuBitmap b;
    bool ptw_nowrite = false;
    bool writable_tlb = false;
    bool old_permission;

    assert(hamt_smc_vcpu_bitmap_init(&b, PAGES));
    assert(hamt_smc_vcpu_bitmap_mark(&b, 0x1000));
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    old_permission = !ptw_nowrite;
    /* IPI invalidates the old TLB and clears the pre-fill bit. */
    hamt_smc_vcpu_bitmap_clear(&b);
    assert(!hamt_smc_vcpu_bitmap_test(&b, 0x1000));
    writable_tlb = old_permission;
    assert(hamt_smc_vcpu_bitmap_mark(&b, 0x1000));
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    assert(hamt_smc_vcpu_bitmap_test(&b, 0x1000));
    if (ptw_nowrite) {
        writable_tlb = false;
    }
    assert(writable_tlb);

    /* Protection during the interrupted fill requires the post-fill check. */
    hamt_smc_vcpu_bitmap_clear(&b);
    assert(hamt_smc_vcpu_bitmap_mark(&b, 0x1000));
    old_permission = !ptw_nowrite;
    ptw_nowrite = true;
    hamt_smc_vcpu_bitmap_clear(&b);
    writable_tlb = old_permission;
    assert(hamt_smc_vcpu_bitmap_mark(&b, 0x1000));
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    if (ptw_nowrite) {
        writable_tlb = false;
    }
    assert(!writable_tlb);
    hamt_smc_vcpu_bitmap_destroy(&b);
}

int main(void)
{
    HamtSmcVcpuBitmap other = { 0 };
    pthread_t workers[THREADS];

    assert(!hamt_smc_vcpu_bitmap_init(&bitmap, 0));
    assert(!hamt_smc_vcpu_bitmap_init(&bitmap, SIZE_MAX));
    assert(hamt_smc_vcpu_bitmap_test(&bitmap, 0));
    assert(hamt_smc_vcpu_bitmap_init(&bitmap, PAGES));
    assert(hamt_smc_vcpu_bitmap_init(&other, PAGES));
    assert(bitmap.word_count == 3);
    assert(!hamt_smc_vcpu_bitmap_test(&bitmap, 129ULL << 12));
    assert(hamt_smc_vcpu_bitmap_mark(&bitmap, 129ULL << 12));
    assert(bitmap.high_water == 3);
    assert(hamt_smc_vcpu_bitmap_test(&bitmap, (129ULL << 12) + 4095));
    assert(!hamt_smc_vcpu_bitmap_test(&other, 129ULL << 12));
    assert(!hamt_smc_vcpu_bitmap_mark(&bitmap, 130ULL << 12));
    assert(hamt_smc_vcpu_bitmap_test(&bitmap, 130ULL << 12));

    for (uintptr_t i = 0; i < THREADS; i++) {
        assert(!pthread_create(&workers[i], NULL, mark_bit, (void *)i));
    }
    for (unsigned i = 0; i < THREADS; i++) {
        assert(!pthread_join(workers[i], NULL));
        assert(hamt_smc_vcpu_bitmap_test(&bitmap, (uint64_t)i << 12));
    }
    assert(hamt_smc_vcpu_bitmap_mark(&other, 0));
    hamt_smc_vcpu_bitmap_clear(&bitmap);
    assert(bitmap.high_water == 3);
    for (unsigned i = 0; i < THREADS; i++) {
        assert(!hamt_smc_vcpu_bitmap_test(&bitmap, (uint64_t)i << 12));
    }
    assert(hamt_smc_vcpu_bitmap_test(&other, 0));
    test_interrupted_fill();
    test_publication();
    hamt_smc_vcpu_bitmap_destroy(&bitmap);
    hamt_smc_vcpu_bitmap_destroy(&other);
    assert(hamt_smc_vcpu_bitmap_test(&bitmap, 0));
    puts("per-vCPU SMC bitmap tests passed");
    return 0;
}
