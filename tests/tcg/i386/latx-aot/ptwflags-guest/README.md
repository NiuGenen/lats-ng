# HAMT ptwflags guest behavior suite

This suite runs real privileged and unprivileged guest accesses through LATS.
It complements the host state-machine test and the refill-emitter inspection.

| Case | ptwflags path exercised |
|---|---|
| `baseline` | flags clear: normal readable and writable data |
| `smc` | code writes set bit 0 and group NO2M, then execution must use 4K fallback |
| `vga` | VGA memory must retain MMIO/VGA fallback semantics |
| `mmio` | the PCI hole must reject direct HAMT access and use the device path |
| `super_read` | a CPL0 TLB entry must not satisfy a CPL3 supervisor-page read |
| `super_write` | the same page must report a user write fault, not a HAMT bypass |
| `super_write_cold` | a cold CPL3 write must report the same fault without preload |
| `super_exec` | instruction fetch must report a user instruction-fetch fault |
| `readonly_write` | a not-present, read-only user page must report fault error 6 |
| `user_present_readonly_write` | a present read-only user page must report error 7 |

The kernel module exposes an allocated page, one VGA page, and one unassigned
PCI-hole page through `/dev/ptwflags_tlb`. The supervisor mapping clears the
PTE user bit. An ioctl first reads that exact user GVA at CPL0 so the following
CPL3 access specifically tests PLV tagging rather than only a cold refill. The
write cases map the guest VMA read-only; mapping it writable would make the
guest kernel repeatedly try to repair a supervisor-only PTE instead of
delivering the user fault.

Place this directory at `/home/ng/ptwflags-guest` in the test QCOW2 image. The
runner first builds the module and freestanding user modes with `hamt=0`, so
compilation cannot depend on the path under test. It then boots each case with
the ptwflags configuration and a temporary QEMU snapshot. Running the access
case as PID 1 avoids depending on guest fork/wait behavior in the measurement.

From the repository root:

```sh
python3 tests/tcg/i386/latx-aot/ptwflags-guest/run-linux.py \
    --binary build/lats-x86_64 \
    --disk run/ubuntu16s.x64.m2048.spec2k.32.64.ok.img \
    --kernel run/vmlinuz-4.4.0-186-generic-x64 \
    --output run/ptwflags-guest.$(date +%Y%m%d-%H%M%S)
```

The default LATS configuration is `hamtconfig=0x3769` with AOT, TU (`tumode`)
and `tucpopt` disabled. This selects the unified ptwflags 4K/2M refill path and
enables PLV tagging.
The guest permission suite defaults to one vCPU; the separate SMP SMC test
below exercises four vCPUs.
The runner requires each case marker and the expected x86 page-fault error codes
`5` (user read), `6` (not-present user write), `7` (present user write), and
`15` (user instruction fetch).

The reserved permission bits 2 through 6 do not have a natural guest producer;
they are covered by the production-state harness in
`test-hamt-ptwflags.py` and by the emitted refill checks in
`test-hamt-ptwdata1m.py`.

## SMP SMC stress

`smc-smp-stress.c` requires an x86 Linux guest with four online CPUs and a C
compiler with pthreads. It pins the writer to CPU 0 and three executors to
CPUs 1-3. Each of 5,000 rounds writes a new return value and then lets all
three CPUs execute the page. Barriers separate modification and execution.
The `alias` mode maps the same backing page at separate writable and
executable addresses. The `huge` mode requires a 2 MiB transparent huge
page and cycles through its 512 constituent 4 KiB pages. It checks
`AnonHugePages` in `/proc/self/smaps` and fails if the allocation did not
become a huge page.

Inside the guest, build and run the cases:

```sh
gcc -std=gnu11 -O2 -Wall -Wextra -Werror -pthread smc-smp-stress.c -o smc-smp-stress
./smc-smp-stress
./smc-smp-stress alias
./smc-smp-stress huge
```

The bitmap remains experimental. Use `hamtconfig=0x3729,smcbitmap=on` for
the C-only walker or `hamtconfig=0x3769,smcbitmap=on` to include the
generated 4K/2M refill walker. Use `aotsys=0,tumode=off,tucpopt=off` to
isolate JIT-TB tests.

`smcbitmap` defaults to on for supported HAMT configurations and is disabled
with a warning for unsupported configurations.
`smcbitmaprw` defaults to off and records all valid entries; on records only
entries eligible for writes. `smcbitmapflush`
defaults to on and clears the owning vCPU's bitmap after a full hardware TLB
invalidation, not after a partial ASID or page invalidation. Unsupported HAMT
configurations do not enable the selective bitmap path.

The `HAMT SMC bitmap` exit counters describe candidate and selected target
requests, not the number of hardware instructions executed. The separate
`HAMT TLB full invalidations` counters cover instrumented local and IPI full
invalidations only; they do not count partial invalidations.
