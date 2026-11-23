/* SPDX-License-Identifier: GPL-2.0-only */
#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define WORKERS 3
#define ROUNDS 5000
#define HUGE_SIZE (2U * 1024 * 1024)

static pthread_barrier_t phase;
static unsigned char *code_page;
static unsigned char *write_page;
static bool huge;
static uint32_t expected;
static unsigned failures;

static size_t code_offset(unsigned round)
{
    return huge ? (round % (HUGE_SIZE / 4096)) * 4096 : 0;
}

static bool has_huge_page(void *p)
{
    FILE *f = fopen("/proc/self/smaps", "r");
    unsigned long start, end, kb;
    char line[256];
    bool in_mapping = false, found = false;

    if (!f) {
        return false;
    }
    while (fgets(line, sizeof(line), f)) {
        if (sscanf(line, "%lx-%lx", &start, &end) == 2) {
            in_mapping = (uintptr_t)p >= start && (uintptr_t)p < end;
        } else if (in_mapping && sscanf(line, "AnonHugePages: %lu kB", &kb) == 1) {
            found = kb >= HUGE_SIZE / 1024;
            break;
        }
    }
    fclose(f);
    return found;
}

static void pin_cpu(int cpu)
{
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    int rc = pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
    if (rc) {
        fprintf(stderr, "affinity CPU %d: %s\n", cpu, strerror(rc));
        exit(1);
    }
}

static void *execute_worker(void *arg)
{
    int cpu = (int)(intptr_t)arg;

    pin_cpu(cpu);
    for (unsigned i = 0; i < ROUNDS; ++i) {
        pthread_barrier_wait(&phase);
        int (*fn)(void) = (int (*)(void))(code_page + code_offset(i));
        uint32_t actual = (uint32_t)fn();
        if (actual != expected) {
            __atomic_fetch_add(&failures, 1, __ATOMIC_RELAXED);
        }
        pthread_barrier_wait(&phase);
    }
    return NULL;
}

int main(int argc, char **argv)
{
    pthread_t workers[WORKERS];
    long page_size = sysconf(_SC_PAGESIZE);
    bool alias = argc == 2 && !strcmp(argv[1], "alias");
    huge = argc == 2 && !strcmp(argv[1], "huge");

    if (argc > 2 || (argc == 2 && !alias && !huge)) {
        fprintf(stderr, "usage: %s [alias|huge]\n", argv[0]);
        return 1;
    }

    if (page_size < 4096) {
        fprintf(stderr, "invalid page size: %ld\n", page_size);
        return 1;
    }
    if (alias) {
        char path[] = "/tmp/smc-smp-XXXXXX";
        int fd = mkstemp(path);

        if (fd < 0 || unlink(path) || ftruncate(fd, page_size)) {
            perror("alias backing");
            return 1;
        }
        code_page = mmap(NULL, (size_t)page_size, PROT_READ | PROT_EXEC,
                         MAP_SHARED, fd, 0);
        write_page = mmap(NULL, (size_t)page_size, PROT_READ | PROT_WRITE,
                          MAP_SHARED, fd, 0);
        close(fd);
    } else if (huge) {
        size_t reserve_size = 2 * HUGE_SIZE;
        unsigned char *reserve = mmap(NULL, reserve_size,
                                      PROT_READ | PROT_WRITE | PROT_EXEC,
                                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (reserve == MAP_FAILED) {
            perror("huge mmap");
            return 1;
        }
        uintptr_t aligned = ((uintptr_t)reserve + HUGE_SIZE - 1) &
                            ~((uintptr_t)HUGE_SIZE - 1);
        size_t prefix = aligned - (uintptr_t)reserve;
        size_t suffix = reserve_size - prefix - HUGE_SIZE;

        if ((prefix && munmap(reserve, prefix)) ||
            (suffix && munmap((void *)(aligned + HUGE_SIZE), suffix))) {
            perror("huge munmap");
            return 1;
        }
        code_page = (unsigned char *)aligned;
        write_page = code_page;
        if (madvise(code_page, HUGE_SIZE, MADV_HUGEPAGE)) {
            perror("MADV_HUGEPAGE");
            return 1;
        }
        memset(code_page, 0, HUGE_SIZE);
        if (!has_huge_page(code_page)) {
            fprintf(stderr, "SMC_SMP=FAIL huge page unavailable\n");
            return 1;
        }
        puts("SMC_SMP_HUGEPAGE=PASS size=2M");
    } else {
        code_page = mmap(NULL, (size_t)page_size,
                         PROT_READ | PROT_WRITE | PROT_EXEC,
                         MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        write_page = code_page;
    }
    if (code_page == MAP_FAILED) {
        perror("mmap");
        return 1;
    }
    if (write_page == MAP_FAILED) {
        perror("write mmap");
        return 1;
    }
    pin_cpu(0);
    if (pthread_barrier_init(&phase, NULL, WORKERS + 1)) {
        fprintf(stderr, "barrier init failed\n");
        return 1;
    }
    for (int i = 0; i < WORKERS; ++i) {
        int rc = pthread_create(&workers[i], NULL, execute_worker,
                                (void *)(intptr_t)(i + 1));
        if (rc) {
            fprintf(stderr, "pthread_create: %s\n", strerror(rc));
            exit(1);
        }
    }
    for (uint32_t i = 0; i < ROUNDS; ++i) {
        unsigned char insn[] = { 0xb8, 0, 0, 0, 0, 0xc3 };
        size_t offset = code_offset(i);
        expected = 0x13570000U ^ i;
        memcpy(insn + 1, &expected, sizeof(expected));
        memcpy(write_page + offset, insn, sizeof(insn));
        __builtin___clear_cache((char *)code_page + offset,
                                (char *)code_page + offset + sizeof(insn));
        pthread_barrier_wait(&phase);
        pthread_barrier_wait(&phase);
    }
    for (int i = 0; i < WORKERS; ++i) {
        pthread_join(workers[i], NULL);
    }
    pthread_barrier_destroy(&phase);
    if (alias) {
        munmap(write_page, (size_t)page_size);
    }
    munmap(code_page, huge ? HUGE_SIZE : (size_t)page_size);
    if (failures) {
        fprintf(stderr, "SMC_SMP=FAIL mismatches=%u\n", failures);
        return 1;
    }
    printf("SMC_SMP=PASS mode=%s rounds=%u workers=%u\n",
           huge ? "huge" : (alias ? "alias" : "direct"), ROUNDS, WORKERS);
    return 0;
}
