================================================
LATS (LoongArch Architecture Translator System)
================================================

.. image:: https://img.shields.io/badge/license-GPL--2.0-blue.svg
   :target: COPYING
   :alt: GPL-2.0 license

LATS (LoongArch Architecture Translator System) is a high-performance
system-level binary translator for the LoongArch architecture. It runs 64-bit
x86 operating systems on LoongArch hosts and supports 32-bit and 64-bit x86
applications inside those guests.

LATS is based on QEMU 8.1.5 and includes substantial architecture-specific
optimizations. The corresponding upstream QEMU commit is
``20a1b341a0af1fef84cec9e521d33da0e8d9ecf3``; this commit ID matches the
upstream QEMU project. System emulation is considered along three dimensions:
processor emulation through binary translation, memory emulation through an
optimized SoftMMU, and device emulation through QEMU device models with virtio
and IOMMU pass-through support.

`中文版本点击这里 >> <README.rst>`_


Project Background
==================

The user-level binary translator `LAT
<https://github.com/lat-opensource/lat>`_ already enables many x86 applications
to run on LoongArch. A system-level translator provides a more complete
compatibility boundary but traditionally pays a higher performance cost. LATS
targets that cost with system-mode specific translation and memory-management
optimizations. It currently runs Windows 7 smoothly on the 3A6000 platform.


Project Layout
==============

.. code-block:: text

   lats
   ├── latxbuild/                            # build scripts
   ├── hamt/hamt-pm/                         # legacy-world HAMT host kernel module
   ├── accel/tcg/                            # QEMU TCG framework
   ├── tcg/
   │   └── region.c                          # code cache space
   ├── target/i386/
   │   ├── hamt/                             # HAMT implementation
   │   └── latx/                             # binary translator
   │       ├── ir1/                          # IR1: x86 instruction IR
   │       ├── ir2/                          # IR2: LoongArch instruction IR
   │       ├── optimization/                 # EFLAGS, HAMT, RAS optimizations
   │       ├── sbt/                          # AOT support
   │       ├── translator/                   # translation and register allocation
   │       ├── include/                      # LATX internal headers
   │       └── capStone/                     # disassembler
   ├── softmmu/                              # system entry and memory management
   ├── hw/                                   # device emulation
   └── README.en.rst                         # this document


Requirements
============

- Build and run on LoongArch Linux. The guest architecture is 64-bit x86.
- The full optimization path requires LSX, LASX, and LBT_X86 support in the
  host CPU and kernel.
- HAMT requires host kernel support. Platforms using HAMT may also require the
  SFB (Store Fill Buffer) to be disabled.
- Building requires Python 3, Meson, Ninja, GCC/G++, GLib, Pixman, and zlib.
  SPICE, SDL2, slirp, and libusb development packages are needed for the
  default feature set.


Build and Run
=============

See the `build and run guide <docs/build-and-run.md>`_ for details.


Documentation and Feedback
==========================

- `Issue tracker <https://github.com/lat-opensource/lats/issues>`_
- `Contributing guide <CONTRIBUTING.md>`_
- `Contributor list <CONTRIBUTORS.md>`_


License
========

LATS is a secondary development based on QEMU 8.1.5. QEMU as a whole is
released under the GNU General Public License version 2 (GPLv2). Third-party
components retained in this repository remain under the licenses stated in
their respective files. See `COPYING <COPYING>`_, `LICENSE <LICENSE>`_, and
`NOTICE <NOTICE>`_.


Acknowledgments
===============

Special thanks to the QEMU project and its contributors. QEMU provides the
system-emulation foundation for LATS.

------------

For questions or suggestions, please use the `issue tracker
<https://github.com/lat-opensource/lats/issues>`_.
