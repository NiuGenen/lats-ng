# 贡献指南 / Contributing to LATS

LATS 欢迎缺陷修复、兼容性改进、性能优化、测试和文档贡献。提交前请先搜索已有
Issue，避免重复工作；较大的功能或架构调整建议先提交 Issue 说明目标、方案和
影响范围。

LATS welcomes bug fixes, compatibility improvements, performance work, tests,
and documentation. Search existing issues before starting. For a large feature
or architectural change, open an issue first to discuss scope and design.

## 提交 Issue / Reporting Issues

欢迎提交 Issue。清晰的问题报告、复现步骤和验证结果同样是项目的重要贡献。

提交客户机问题或运行错误时，请尽量提供：

- 测试环境：LATS commit、宿主操作系统、内核、KVM 及相关依赖版本。
- 测试节点：宿主 CPU 型号、内存容量、CPU/NUMA 绑定等与问题有关的配置。
- 运行参数：完整启动命令，包括 `-M`、`-m`、`-smp`、`-cpu`、`-display`、
  `-latx`、`LATS_OPT` 等参数。
- 镜像或 ISO：客户机类型和版本、镜像格式、获取或生成方式、必要固件或驱动，
  以及可公开的哈希值。
- 问题现象、预期结果、完整日志和必要的截图。

镜像或日志无法公开时，请提供可复现的镜像构造方法、关键配置和哈希，避免上传
敏感数据或无授权的软件。

如果客户机内部运行出错，建议首先在 x86 机器上使用同一镜像或 ISO，通过
QEMU/KVM 进行对照测试。请尽量保持相同的虚拟硬件、固件和设备配置，并在 Issue
中说明 x86/QEMU-KVM 的测试结果，用于判断问题是否与 LATS 相关。若问题仅在
LATS 上复现，请同时提供两种环境下的配置和日志。

Clear issue reports, reproduction steps, and validation results are valuable
contributions to the project.

When reporting a guest or runtime problem, include as much of the following as
possible:

- Test environment: LATS commit, host OS, kernel, KVM, and relevant dependency
  versions.
- Test node: host CPU model, memory size, CPU/NUMA affinity, and other relevant
  host configuration.
- Runtime parameters: the complete launch command, including `-M`, `-m`,
  `-smp`, `-cpu`, `-display`, `-latx`, `LATS_OPT`, and related options.
- Image or ISO: guest type and version, image format, how it was obtained or
  built, required firmware or drivers, and public hashes where available.
- Observed behavior, expected behavior, complete logs, and relevant screenshots.

If an image or log cannot be shared publicly, provide reproducible build steps,
key configuration, and hashes instead of uploading sensitive data or
unauthorized software.

For errors occurring inside the guest, first reproduce the issue on an x86 host
with QEMU/KVM using the same image or ISO. Keep the virtual hardware, firmware,
and device configuration as similar as possible, and report the x86/QEMU-KVM
result. If the issue reproduces only with LATS, include the configuration and
logs from both environments.

## 开发流程 / Workflow

1. Fork `lat-opensource/lats`，并从 `main` 创建独立主题分支。
2. 保持变更聚焦，避免在同一 Pull Request 中混入无关重构。
3. 在支持 LoongArch 的环境中构建并运行受影响测试。
4. 从个人 Fork 向上游 `master` 提交 Pull Request，并说明验证结果。

```console
git clone https://github.com/YOUR_ACCOUNT/lats.git
cd lats
git remote add upstream https://github.com/lat-opensource/lats.git
git fetch upstream
git switch -c TOPIC_BRANCH upstream/main
```

1. Fork `lat-opensource/lats` and create a topic branch from `main`.
2. Keep each pull request focused and avoid unrelated refactoring.
3. Build and test the affected functionality on a LoongArch-capable host.
4. Open the pull request from your fork to upstream `master` and describe the
   validation performed.

## DCO 签署 / Developer Certificate of Origin

每个提交都必须包含 Developer Certificate of Origin 1.1 的
`Signed-off-by` 尾注。签署表示你确认有权按本项目的 GPLv2 兼容许可证提交该
贡献。

Every commit must include a `Signed-off-by` trailer for Developer Certificate
of Origin 1.1. The sign-off certifies that you have the right to submit the
contribution under a GPLv2-compatible license.

```console
git commit -s -m "component: concise description"
```

`Signed-off-by` 中的姓名和邮箱应与提交作者一致。自动化工具或 AI 助手不得在
未经作者明确确认和授权的情况下代为添加 `Signed-off-by`。

The name and email in the sign-off must match the commit author. Automation
and AI assistants must not add a sign-off without the author's explicit review
and authorization.

## 构建与测试 / Build and Test

```console
./latxbuild/build.sh -c def
python3 tests/tcg/i386/latx-aot/ras-tp-bench/run-regressions.py
```

并非所有测试都能在 x86 主机运行。涉及系统翻译、HAMT、AOT 和客户机启动的
变更需要在 LoongArch 主机上验证；如果无法执行某项测试，请在 Pull Request
中明确说明原因。

Not every test can run on an x86 host. Changes involving system translation,
HAMT, AOT, or guest boot need validation on a LoongArch host. If a test cannot
be run, state the reason in the pull request.

## 许可证 / Licensing

提交的代码必须与本项目现有许可证兼容。新增第三方代码时，请保留原始版权和
许可证信息，并同步更新 `NOTICE`。请勿提交无授权的专有代码、二进制文件或
测试数据。

Contributions must be compatible with the project's existing licenses. Preserve
original copyright and license notices when adding third-party code, and update
`NOTICE` as needed. Do not submit unauthorized proprietary code, binaries, or
test data.
