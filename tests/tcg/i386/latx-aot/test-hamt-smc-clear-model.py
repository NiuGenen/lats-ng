#!/usr/bin/env python3
"""Enumerate sequentially consistent SMC fill/protect/interrupt schedules.

This model checks the protocol ordering, not LoongArch instructions, memory
barriers, the production IPI handler, aliases, or the complete SMC lifecycle.
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class State:
    fill: int = 0
    protect: int = 0
    unrelated_ipi: bool = False
    mark: bool = False
    nowrite: bool = False
    before: bool = False
    writable: bool = False
    selected: bool = False


def fill_step(s, republish):
    if s.fill == 0:
        return replace(s, fill=1, mark=True)
    if s.fill == 1:
        return replace(s, fill=2, before=s.nowrite)
    if s.fill == 2:
        return replace(s, fill=3, writable=not s.before)
    if s.fill == 3:
        return replace(s, fill=4, mark=(s.mark or (republish and s.writable)))
    if s.fill == 4:
        return replace(s, fill=5, writable=s.writable and not s.nowrite)
    raise AssertionError("fill already completed")


def protect_step(s):
    if s.protect == 0:
        return replace(s, protect=1, nowrite=True)
    if s.protect == 1:
        return replace(s, protect=2, selected=s.mark)
    if s.protect == 2:
        return replace(s, protect=3,
                       mark=False if s.selected else s.mark,
                       writable=False if s.selected else s.writable)
    raise AssertionError("protection already completed")


def explore(republish):
    seen = set()
    failures = []

    def visit(s, trace):
        if s in seen:
            return
        seen.add(s)
        if s.fill == 5 and s.protect == 3 and s.unrelated_ipi:
            if s.writable:
                failures.append(trace)
            return
        if s.fill < 5:
            visit(fill_step(s, republish), trace + ("fill",))
        if s.protect < 3:
            visit(protect_step(s), trace + ("protect",))
        if not s.unrelated_ipi:
            # IPI executes on the filler vCPU, invalidates, then clears.
            visit(replace(s, unrelated_ipi=True, mark=False, writable=False),
                  trace + ("ipi",))

    visit(State(), ())
    return len(seen), failures


def sibling_race(irq_slot, masked):
    # Protection is waiting for an IPI while a paired TLB update is in flight.
    sibling = True
    saved = False
    pending = False
    acknowledged = False
    for step in range(3):
        if irq_slot == step:
            if masked and step == 1:
                pending = True
            else:
                sibling = False
                acknowledged = True
        if step == 0:  # tlbrd saves the sibling half
            saved = sibling
        elif step == 1:  # tlbwr restores it
            sibling = saved
        elif pending:
            sibling = False
            acknowledged = True
    return acknowledged and sibling


@dataclass(frozen=True)
class NoBitmapState:
    fill: int = 0
    protect: int = 0
    nowrite: bool = False
    old_writable: bool = False
    writable_tlb: bool = False


def explore_no_bitmap(recheck):
    seen = set()
    failures = []

    def visit(s, trace):
        if s in seen:
            return
        seen.add(s)
        if s.fill == 3 and s.protect == 2:
            if s.writable_tlb:
                failures.append(trace)
            return
        if s.fill == 0:
            visit(replace(s, fill=1, old_writable=not s.nowrite), trace + ("read",))
        elif s.fill == 1:
            visit(replace(s, fill=2, writable_tlb=s.old_writable), trace + ("fill",))
        elif s.fill == 2:
            visit(replace(s, fill=3,
                          writable_tlb=s.writable_tlb and not (recheck and s.nowrite)),
                  trace + ("recheck",))
        if s.protect == 0:
            visit(replace(s, protect=1, nowrite=True), trace + ("protect",))
        elif s.protect == 1:
            visit(replace(s, protect=2, writable_tlb=False), trace + ("ipi",))

    visit(NoBitmapState(), ())
    return len(seen), failures


def ipi_lost_after_early_ack(clear_before_ack):
    # One source issues requests serially; the target handles the first one.
    pending = True
    observed = pending
    if clear_before_ack:
        pending = pending and not observed
    acknowledged = True
    if acknowledged:
        # The source can submit another request immediately after the ack.
        pending = True
    if not clear_before_ack:
        pending = pending and not observed
    return not pending


def ipi_ack_before_invalidation(snapshot_before_invalidate):
    # A second source sends after the first invalidation. Its protection
    # must not be acknowledged by that earlier invalidation.
    pending = {0}
    if snapshot_before_invalidate:
        observed = pending.copy()
        pending -= observed
    pending.add(1)
    if not snapshot_before_invalidate:
        observed = pending.copy()
        pending -= observed
    return 1 in observed


def paused_target_reuses_ack_slot():
    # The first sender stops waiting when the target is not running.
    pending = True
    first_sender_returned = True
    # The target snapshots and clears request 1, then invalidates.
    observed = pending
    pending = False
    invalidation = 1
    # Sender protects a second page and reuses the same ack slot.
    protection = 2
    pending = True
    # The delayed acknowledgement for request 1 lands in request 2's slot.
    ack = observed and first_sender_returned
    return ack and pending and invalidation < protection


def sequenced_retry():
    # Target handles an older bit, snapshots generation 1 and flushes.
    request = 1
    observed = request
    invalidated_for = observed
    # A new protection publishes generation 2 before the old ack is stored.
    request = 2
    ack = observed
    assert ack != request and invalidated_for < request
    # Retrying the coalesced bit makes the target observe and flush generation 2.
    observed = request
    invalidated_for = observed
    ack = observed
    return ack == request and invalidated_for == request


@dataclass(frozen=True)
class ResumeState:
    protector: int = 0
    target: int = 0
    running: bool = False
    deferred: bool = False
    flushed: bool = False
    wait_for_ack: bool = False


def explore_deferred_resume():
    # Proposed handshake, not yet implemented. Both sides require a full
    # barrier between their store and subsequent load.
    seen = set()
    unsafe = []

    def visit(s, trace):
        if s in seen:
            return
        seen.add(s)
        if s.protector == 2 and s.target == 3:
            if not s.flushed and not s.wait_for_ack:
                unsafe.append(trace)
            return
        if s.protector == 0:
            visit(replace(s, protector=1, deferred=True), trace + ("defer",))
        elif s.protector == 1:
            visit(replace(s, protector=2, wait_for_ack=s.running),
                  trace + ("check-running",))
        if s.target == 0:
            visit(replace(s, target=1, running=True), trace + ("start",))
        elif s.target == 1:
            visit(replace(s, target=2, flushed=s.deferred, deferred=False),
                  trace + ("consume-deferred",))
        elif s.target == 2:
            visit(replace(s, target=3), trace + ("guest-entry",))

    visit(ResumeState(), ())
    return len(seen), unsafe


def main():
    _, unsafe = explore(False)
    assert unsafe, "model must reproduce lost pre-fill mark"
    states, unsafe = explore(True)
    assert not unsafe, f"writable protected page in schedule {unsafe[:1]}"
    assert sibling_race(1, False), "model must reproduce stale sibling"
    assert not any(sibling_race(slot, True) for slot in range(3))
    _, unsafe = explore_no_bitmap(False)
    assert unsafe, "model must reproduce an IPI before an untracked fill"
    no_bitmap_states, unsafe = explore_no_bitmap(True)
    assert not unsafe, f"untracked writable protected page: {unsafe[:1]}"
    assert ipi_lost_after_early_ack(False), "model must reproduce lost IPI"
    assert not ipi_lost_after_early_ack(True), "late IPI must stay pending"
    assert ipi_ack_before_invalidation(False), "model must reproduce early flush"
    assert not ipi_ack_before_invalidation(True), "late request must not be acked"
    assert paused_target_reuses_ack_slot(), "model must reproduce stale ack"
    assert sequenced_retry(), "generation protocol must reject the old ack"
    resume_states, unsafe = explore_deferred_resume()
    assert not unsafe, f"proposed deferred-resume handshake fails: {unsafe[:1]}"
    print(f"PASS: post-fill publication model, {states} states; "
          "missing-publication counterexample reproduced")
    print("PASS: paired TLB update model; stale-sibling counterexample reproduced")
    print(f"PASS: bitmap-off recheck model, {no_bitmap_states} states; "
          "early-IPI counterexample reproduced")
    print("PASS: clear-before-ack model; lost-IPI counterexample reproduced")
    print("PASS: old paused-target protocol reproduces stale acknowledgement")
    print("PASS: generation retry model rejects stale acknowledgement")
    print(f"PASS: deferred-resume ordering model, {resume_states} states")


if __name__ == "__main__":
    main()
