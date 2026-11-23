/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "hamt-smc-bitmap.h"

#define ROUNDS 50000
#define THREADS 16

static uint32_t pages[1024];
static uint32_t groups[4];
static HamtSmcBitmap bitmap = { .page4k = pages, .page4k_count = 1024,
                                .page1m = groups, .page1m_count = 4 };
static pthread_barrier_t start, finish;
static unsigned char protected_page;
static int fill_saw_protected;
static uint32_t protect_saw_mask;

static void *filler(void *unused)
{
    (void)unused;
    for (int i = 0; i < ROUNDS; i++) {
        pthread_barrier_wait(&start);
        assert(hamt_smc_bitmap_mark(&bitmap, i & 1 ? 0 : 0x3000,
                                    i & 1 ? 20 : 12, 3));
        hamt_smc_bitmap_publish();
        fill_saw_protected = __atomic_load_n(&protected_page,
                                             __ATOMIC_RELAXED);
        pthread_barrier_wait(&finish);
    }
    return NULL;
}

static void *protector(void *unused)
{
    (void)unused;
    for (int i = 0; i < ROUNDS; i++) {
        pthread_barrier_wait(&start);
        __atomic_store_n(&protected_page, 1, __ATOMIC_RELAXED);
        hamt_smc_bitmap_publish();
        protect_saw_mask = hamt_smc_bitmap_mask(&bitmap, 0x3000);
        pthread_barrier_wait(&finish);
    }
    return NULL;
}

static void *mark_same_page(void *arg)
{
    unsigned cpu = (uintptr_t)arg;
    for (int i = 0; i < 10000; i++) {
        assert(hamt_smc_bitmap_mark(&bitmap, 0x2000, 12, cpu));
    }
    return NULL;
}

/* An IPI can flush after the first flags read, before the TLB write. */
static void test_fill_interrupted_by_ipi(void)
{
    uint32_t local_pages[2] = { 0 }, local_groups[1] = { 0 };
    HamtSmcBitmap b = { .page4k = local_pages, .page4k_count = 2,
                        .page1m = local_groups, .page1m_count = 1 };
    unsigned char flags = 0;
    bool writable_tlb = false;
    bool flags_before_fill;

    assert(hamt_smc_bitmap_mark(&b, 0x1000, 12, 1));
    hamt_smc_bitmap_publish();
    flags_before_fill = __atomic_load_n(&flags, __ATOMIC_RELAXED);
    assert(!flags_before_fill);

    __atomic_store_n(&flags, 1, __ATOMIC_RELAXED);
    hamt_smc_bitmap_publish();
    assert(hamt_smc_bitmap_mask(&b, 0x1000) & (1u << 1));

    /* IPI flush completes before the interrupted filler resumes. */
    writable_tlb = false;
    writable_tlb = !flags_before_fill;
    assert(writable_tlb);
    hamt_smc_bitmap_publish();
    if (__atomic_load_n(&flags, __ATOMIC_RELAXED)) {
        writable_tlb = false;
    }
    assert(!writable_tlb);
}

typedef struct PendingTest {
    HamtSmcBitmap *bitmap;
    pthread_barrier_t published;
    pthread_barrier_t observed;
    unsigned char flags;
} PendingTest;

static void *protect_first(void *arg)
{
    PendingTest *t = arg;

    assert(hamt_smc_protect_begin(t->bitmap, 0));
    __atomic_store_n(&t->flags, 1, __ATOMIC_SEQ_CST);
    pthread_barrier_wait(&t->published);
    pthread_barrier_wait(&t->observed);
    hamt_smc_protect_end(t->bitmap, 0);
    return NULL;
}

static void test_pending_protection(HamtSmcBitmap *bitmap)
{
    PendingTest t = { .bitmap = bitmap };
    pthread_t first;

    assert(!pthread_barrier_init(&t.published, NULL, 2));
    assert(!pthread_barrier_init(&t.observed, NULL, 2));
    assert(!pthread_create(&first, NULL, protect_first, &t));
    pthread_barrier_wait(&t.published);
    assert(__atomic_load_n(&t.flags, __ATOMIC_RELAXED));
    assert(hamt_smc_protect_pending(bitmap, 0));
    pthread_barrier_wait(&t.observed);
    assert(!pthread_join(first, NULL));
    assert(!hamt_smc_protect_pending(bitmap, 0));
    assert(!pthread_barrier_destroy(&t.published));
    assert(!pthread_barrier_destroy(&t.observed));
}

int main(void)
{
    pthread_t workers[THREADS], fill, protect;
    HamtSmcBitmap allocated;

    assert(!hamt_smc_bitmap_init(&allocated, 0));
    assert(hamt_smc_bitmap_mask(&allocated, 0) == UINT32_MAX);
    assert(!hamt_smc_bitmap_init(&allocated, SIZE_MAX));
    assert(hamt_smc_bitmap_mask(&allocated, 0) == UINT32_MAX);
    assert(hamt_smc_bitmap_init(&allocated, 257));
    assert(allocated.page1m_count == 2);
    assert(!hamt_smc_protect_pending(&allocated, 0));
    assert(hamt_smc_protect_begin(&allocated, 0));
    assert(hamt_smc_protect_begin(&allocated, 0));
    assert(hamt_smc_protect_pending(&allocated, 0));
    hamt_smc_protect_end(&allocated, 0);
    assert(hamt_smc_protect_pending(&allocated, 0));
    hamt_smc_protect_end(&allocated, 0);
    assert(!hamt_smc_protect_pending(&allocated, 0));
    test_pending_protection(&allocated);
    assert(hamt_smc_bitmap_mask(&allocated, 256 * 4096) == 0);
    assert(hamt_smc_bitmap_mark(&allocated, 256 * 4096, 12, 7));
    assert(hamt_smc_bitmap_mark(&allocated, 0, 20, 3));
    assert(hamt_smc_bitmap_mask(&allocated, 0x1000) == (1u << 3));
    assert(hamt_smc_bitmap_mask(&allocated, 256 * 4096) == (1u << 7));
    hamt_smc_bitmap_destroy(&allocated);
    assert(hamt_smc_bitmap_mask(&allocated, 0) == UINT32_MAX);

    uint32_t fallback_pages[1] = { 0 }, fallback_groups[1] = { 0 };
    HamtSmcBitmap fallback = { .page4k = fallback_pages, .page4k_count = 1,
                               .page1m = fallback_groups, .page1m_count = 1 };
    assert(!hamt_smc_protect_pending(&fallback, 0));
    assert(hamt_smc_protect_begin(&fallback, 0));
    assert(hamt_smc_protect_begin(&fallback, 0x1000));
    assert(hamt_smc_protect_pending(&fallback, 0));
    hamt_smc_protect_end(&fallback, 0);
    assert(hamt_smc_protect_pending(&fallback, 0));
    hamt_smc_protect_end(&fallback, 0x1000);
    assert(!hamt_smc_protect_pending(&fallback, 0));
    assert(hamt_smc_bitmap_mark(&bitmap, 0x1000, 12, 0));
    assert(hamt_smc_bitmap_mark(&bitmap, 0x200000, 20, 5));
    assert(hamt_smc_bitmap_mask(&bitmap, 0x1000) == 1);
    assert(hamt_smc_bitmap_mask(&bitmap, 0x1001) == 1);
    assert(hamt_smc_bitmap_mask(&bitmap, 0x2000) == 0);
    assert(hamt_smc_bitmap_mask(&bitmap, 0x2ff000) == (1u << 5));
    assert(hamt_smc_bitmap_mask(&bitmap, 0x400000) == UINT32_MAX);
    assert(!hamt_smc_bitmap_mark(&fallback, 0x400000, 12, 2));
    assert(hamt_smc_bitmap_mask(&fallback, 0) == (1u << 2));

    test_fill_interrupted_by_ipi();
    assert(!hamt_smc_bitmap_mark(&fallback, 0, 21, 4));
    assert(hamt_smc_bitmap_mask(&fallback, 0) == ((1u << 2) | (1u << 4)));
    assert(!hamt_smc_bitmap_mark(&fallback, 0, 64, 6));
    assert(hamt_smc_bitmap_mask(&fallback, 0) ==
           ((1u << 2) | (1u << 4) | (1u << 6)));
    assert(!hamt_smc_bitmap_mark(&fallback, 0, 12, 32));
    assert(hamt_smc_bitmap_mask(&fallback, 0) == UINT32_MAX);

    for (unsigned i = 0; i < THREADS; i++) {
        assert(!pthread_create(&workers[i], NULL, mark_same_page,
                               (void *)(uintptr_t)i));
    }
    for (unsigned i = 0; i < THREADS; i++) {
        assert(!pthread_join(workers[i], NULL));
    }
    assert(hamt_smc_bitmap_mask(&bitmap, 0x2000) == 0xffff);

    assert(!pthread_barrier_init(&start, NULL, 3));
    assert(!pthread_barrier_init(&finish, NULL, 3));
    assert(!pthread_create(&fill, NULL, filler, NULL));
    assert(!pthread_create(&protect, NULL, protector, NULL));
    for (int i = 0; i < ROUNDS; i++) {
        __atomic_store_n(&pages[3], 0, __ATOMIC_RELAXED);
        __atomic_store_n(&groups[0], 0, __ATOMIC_RELAXED);
        __atomic_store_n(&protected_page, 0, __ATOMIC_RELAXED);
        pthread_barrier_wait(&start);
        pthread_barrier_wait(&finish);
        assert(fill_saw_protected || (protect_saw_mask & (1u << 3)));
    }
    assert(!pthread_join(fill, NULL));
    assert(!pthread_join(protect, NULL));
    assert(!pthread_barrier_destroy(&start));
    assert(!pthread_barrier_destroy(&finish));
    puts("SMC bitmap tests passed");
    return 0;
}
