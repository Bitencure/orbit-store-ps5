<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Sandbox build: what it can write, and what it cannot touch

Scope: `orbit_store_sandbox.elf`, i.e. the service built with `-DORBIT_SANDBOX` and without the launcher code (`make sandbox`).
Method: reading every filesystem-mutating call in `backend/`, comparing the two ELFs' imports, and running the
integration tests against the sandbox flags inside a jail that makes everything but two folders read-only.
Nothing here was run on a PS5.

## Result

The sandbox writes in **two places only**:

1. its own state folder `/data/orbit-store-fork-test/` (everything is `openat` relative to that folder's descriptor), and
2. `<drive>/homebrew/` of the drive chosen for a download (partial `.part` files, the finished file, a
   `.orbit-write-<random>.tmp` probe that is unlinked at once, and extraction staging for `.zip/.7z/.rar`).

## 1. Code review

| Area | Writes | Reaches the installed Orbit? |
|---|---|---|
| `state.c`, `custom.c`, `debrid.c`, `catalog.c`, `archive_account.c`, `receive.c`, `diagnostics.c`, `main.c` (lock) | files in the state descriptor only (`state.json`, `custom-catalogue.json`, `debrid.json` (the TorBox key), `catalogue.json`, `archive-account.json`, `receive*.json`, `startup-status.json`, `instance.lock`) | No: a different folder, a different lock. |
| `zero_companion.c` | `zero-companion.json` under `orbit.state_dir` | No. |
| `transfer.c`, `queue.c`, `storage.c`, `extract.c`, `receive.c` (file data) | `<drive>/homebrew/…`, via the descriptor `storage_open` returns after checking the drive's device and inode | Only through that shared folder. Existing files are never overwritten. |
| `autoboot.c` (payload-manager and autoload copies, `/data/orbit-store/orbit_store.elf`, the homebrew-launcher entry) | The three entry points (`autoboot_install`, `autoboot_set`, `integration_set`) return before doing anything when `orbit.autoboot` is false, and the sandbox sets it false. The startup call to `autoboot_sync` is compiled out (`ORBIT_INSTALL_LAUNCHER && !ORBIT_SANDBOX`); the one other call, on the "already running" path, only reads the saved version and then returns through the same gate. | Cannot. |
| `tvapp.c` (writes `/data/homebrew/PPSA99177.ffpkg`) | Its worker acts only on an action set by `tvapp_action`, which answers 409 unless `orbit.autoboot`. | Cannot. |
| `updates.c` (network checks, saving a newer ELF) | Same: the worker only acts on `updates_action`, gated by `orbit.autoboot`. The one exception is deliberate: **stop** is allowed in the sandbox so the test build can be shut down from its page. | Cannot update or replace anything. |
| `launcher/` (`ORBT00001` icon registration under `/user/app`) | Not compiled into the sandbox. | Cannot. |
| `ps5_fs.c` | Raw `*at` syscall stubs with no path rewriting. | n/a |

Other side effects that are not file writes:

- **Console toast** (`sceKernelSendNotificationRequest`): says TEST BUILD.
- **PS5 browser**: opened (`sceSystemServiceLaunchWebBrowser`) only after you press a browser-assisted button. While that session
  is open Orbit reads the browser process's memory with `kernel_proc_copyout`, read-only and throttled; the code says "no ptrace, writes,
  code injection or process kills". This is upstream's mechanism and is identical in the installed Orbit.
- **ShadowMount**: the Library page's actions (`scan`, mount, move, copy) are HTTP calls to ShadowMount, and only run when you press
  them. **Do not use the Library page during the test.** Read-only status polling is harmless.
- **Network**: the service listens on every interface, port 34178, behind the same pairing-code token as the installed Orbit. The
  Host header must carry that port.

## 2. The ELF itself

- **Imports.** The sandbox's dynamic imports are the regular ELF's minus exactly `sceAppInstUtilInitialize`,
  `sceAppInstUtilAppInstallAll` and `sceAppInstUtilTerminate`, the calls that register a home-screen title. Nothing was added.
  The platform imports it keeps: `sceKernelSendNotificationRequest`, `sceNetResolver*`, `sceNetPool*`, `sceNetErrnoLoc`, `sysconf`, `sysctl`.
- **Defaults compiled in.** The `orbit` struct in the sandbox's data section holds port 34178 (34177 in the regular ELF), and the string
  `/data/orbit-store-fork-test` appears once in the sandbox and nowhere in the regular ELF.

## 3. Enforcement run (host build)

`tools/fork/audit-writes.sh` runs the whole integration suite against `build/orbit-sandbox-test` inside a `bwrap` jail where the whole
filesystem is read-only except the service's state and storage folders, with `tools/fork/wrlog.c` (an `LD_PRELOAD` shim) logging
every filesystem mutation libc is asked for. Result on this build: **58 tests run, 56 passed, 2 skipped on purpose** (they test
the non-sandbox binary), and of **4,368 logged mutations none was outside the state and storage folders**. In the state folder
they were `state.json`, `custom-catalogue.json`, `debrid.json`, `startup-status.json` and `instance.lock` (each with its temporary
file); in storage, only paths under `homebrew/`.

This run cannot see code that exists only in the PS5 build (the toast, the browser launch and memory reads, the ShadowMount
client); those were covered by the review above.

## What this does not establish

- That the ELF runs on 13.60 with your loader, or that it is free of crashes or console hangs. A payload runs with the loader's
  privileges, so a bug in unaudited code could in principle do harm that file-write analysis cannot see.
- That your ELF loader leaves the installed Orbit running when it is sent a second payload (test 2 in `FIRST-TEST.md` finds out).
- That the shared `homebrew/` folder is free of name clashes with other tools: use the unique `orbit-fork-test-` names.
