/* SPDX-License-Identifier: GPL-2.0-only */
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define ROUNDS 1000
#define PAGE 4096

static unsigned char *page_a, *page_b;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static unsigned phase;
static uint32_t worker_value;

static void pin_cpu(int cpu)
{
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (pthread_setaffinity_np(pthread_self(), sizeof(set), &set)) {
        fprintf(stderr, "SMC_IDLE=FAIL cpu affinity %d\n", cpu);
        exit(1);
    }
}

static void set_code(unsigned char *page, uint32_t value)
{
    unsigned char insn[] = { 0xb8, 0, 0, 0, 0, 0xc3 };
    memcpy(insn + 1, &value, sizeof(value));
    memcpy(page, insn, sizeof(insn));
    __builtin___clear_cache((char *)page, (char *)page + sizeof(insn));
}

static uint32_t execute(unsigned char *page)
{
    return (uint32_t)((int (*)(void))page)();
}

static void wait_phase(unsigned expected)
{
    while (phase != expected) {
        pthread_cond_wait(&changed, &lock);
    }
}

static void *worker(void *unused)
{
    (void)unused;
    pin_cpu(1);
    for (unsigned i = 0; i < ROUNDS; i++) {
        pthread_mutex_lock(&lock);
        wait_phase(1);
        /* Make both pages writable in this vCPU before it blocks. */
        *(volatile unsigned char *)page_a = *(volatile unsigned char *)page_a;
        *(volatile unsigned char *)page_b = *(volatile unsigned char *)page_b;
        phase = 2;
        pthread_cond_signal(&changed);
        wait_phase(3);
        set_code(page_b, worker_value);
        phase = 4;
        pthread_cond_signal(&changed);
        pthread_mutex_unlock(&lock);
    }
    return NULL;
}

int main(void)
{
    pthread_t thread;
    unsigned failures = 0;

    page_a = mmap(NULL, PAGE, PROT_READ | PROT_WRITE | PROT_EXEC,
                  MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    page_b = mmap(NULL, PAGE, PROT_READ | PROT_WRITE | PROT_EXEC,
                  MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (page_a == MAP_FAILED || page_b == MAP_FAILED) {
        perror("mmap");
        return 1;
    }
    pin_cpu(0);
    if (pthread_create(&thread, NULL, worker, NULL)) {
        fprintf(stderr, "SMC_IDLE=FAIL pthread_create\n");
        return 1;
    }
    for (unsigned i = 0; i < ROUNDS; i++) {
        uint32_t initial = 0x10000000U ^ i;
        uint32_t protected_value = 0x20000000U ^ i;

        pthread_mutex_lock(&lock);
        set_code(page_a, initial);
        set_code(page_b, initial);
        phase = 1;
        pthread_cond_signal(&changed);
        wait_phase(2);
        pthread_mutex_unlock(&lock);

        /* Give the other vCPU an opportunity to enter its idle path. */
        usleep(1000);
        if (execute(page_a) != initial || execute(page_b) != initial) {
            failures++;
        }
        set_code(page_a, protected_value);
        set_code(page_b, protected_value);
        if (execute(page_a) != protected_value ||
            execute(page_b) != protected_value) {
            failures++;
        }
        pthread_mutex_lock(&lock);
        worker_value = 0x30000000U ^ i;
        phase = 3;
        pthread_cond_signal(&changed);
        wait_phase(4);
        if (execute(page_b) != worker_value) {
            failures++;
        }
        phase = 0;
        pthread_mutex_unlock(&lock);
    }
    pthread_join(thread, NULL);
    munmap(page_a, PAGE);
    munmap(page_b, PAGE);
    if (failures) {
        fprintf(stderr, "SMC_IDLE=FAIL mismatches=%u\n", failures);
        return 1;
    }
    printf("SMC_IDLE=PASS rounds=%u\n", ROUNDS);
    return 0;
}
