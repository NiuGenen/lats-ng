#!/bin/sh
set -u

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PATH=/usr/lib/gcc/x86_64-linux-gnu/5:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
rc=0

mount -t proc proc /proc || rc=1
mount -t sysfs sysfs /sys || rc=1
if [ "$rc" -eq 0 ]; then
    gcc -std=gnu11 -O2 -Wall -Wextra -Werror -pthread \
        "$dir/smc-smp-stress.c" -o "$dir/smc-smp-stress" || rc=1
    gcc -std=gnu11 -O2 -Wall -Wextra -Werror -pthread \
        "$dir/smc-idle-stress.c" -o "$dir/smc-idle-stress" || rc=1
fi
if [ "$rc" -eq 0 ]; then
    case "${1:-all}" in
        all)
            "$dir/smc-smp-stress" || rc=1
            "$dir/smc-smp-stress" alias || rc=1
            "$dir/smc-smp-stress" huge || rc=1
            "$dir/smc-idle-stress" || rc=1
            ;;
        idle)
            "$dir/smc-idle-stress" || rc=1
            ;;
        *)
            echo "SMC_SMP=FAIL unknown suite: $1"
            rc=1
            ;;
    esac
fi
echo "SMC_SMP_SUITE_RESULT=$rc"
sync
/sbin/poweroff -f
exit "$rc"
