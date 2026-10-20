<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Orbit Zero and this fork

Short answer: **Orbit Zero 1.3.5 cannot use the pasted-link feature, and nothing in this fork changes it.** The
browser interface served by the PS5 is a reasonable replacement for pasted links. Everything below comes from reading
the distributed app; Zero was **not run** and nothing was changed.

## What was looked at

- `Orbit-Zero-1.3.5-linux-x64.tar.gz` from upstream's v1.3.5 release (sha256 `bca56189…1a46e`, matches upstream's
  `SHA256SUMS`), unpacked into a scratch folder.
- It is an Electron app. Its JavaScript ships in `resources/app.asar`, so it can be read. Its `package.json` says
  `"license": "UNLICENSED"`, so this fork does not copy, patch or redistribute any of it. Only file names and the
  calls it makes to the console were noted, to see whether the two programs can work together.
- Upstream's source bundle still does not contain Zero's source, so a change to Zero is not something this fork can
  offer.

## What Zero does

- Zero downloads **on the computer** and pushes the file to the PS5 over the console's receive endpoints
  (`/api/v1/receive`, `/receive/chunk`, `/receive/finish`, `/receive/abandon`).
- It ships its own copy of upstream's `orbit_store.elf` (pinned by sha256 in `resources/orbit/receiver.json`). Its
  "start Orbit" action sends that file to the console's ELF loader (default port 9021) or to Payload Manager (8084), and
  may fetch a newer official one from upstream's `payloads.json`. It also has a "custom ELF" choice.
- The calls it makes to the console service are: `/system`, `/storage`, `/pair`, `/pair/show`, `/receive…`,
  `/downloads` (list, and create **by catalogue release id**), `/zero/probe`, `/zero/companion`, `/favorites`,
  `/library`. It keeps its own copy of upstream's catalogue instead of asking the console for one.

## What that means for the fork

| Question | Answer |
|---|---|
| Can Zero use `/api/v1/custom/resolve` or paste a URL? | **No.** It never calls `/custom/*`, has no field for a URL, and only submits release ids from its own upstream catalogue copy, which never contain a pasted link. |
| Will Zero still connect to the fork's service? | **Probably.** It only checks that `/system` reports the name `Orbit Store`, then relies on `receiveProtocol` 1 and `receiveAvailable`. The fork keeps all three. Not tried against a console. |
| Do computer-to-PS5 transfers still work? | The fork did not touch the receive code, so they should. **Not tried.** |
| Will a pasted-link job in the console's list confuse Zero? | Reading its list code: a job whose release id is not in Zero's catalogue just gets an empty source-page link, so it should show without breaking the list. **Not observed.** |
| Will Zero's **start Orbit** replace the fork? | Yes, if it sends its bundled **official** ELF, and the official ELF saves itself over the fork's saved copy. Use Zero's custom-ELF option, or send the fork's file yourself. For the first test, **do not use Zero to start anything**. |
| Does Zero work with the first-test (sandbox) build? | Do not try it. The sandbox listens on port 34178 and has its own pairing; Zero assumes 34177. If Zero has unfinished transfers it will keep them, but there is nothing to gain. |

## The browser interface as the alternative

Any browser on your network can open `http://<PS5 address>:34177/` (`:34178` for the sandbox build), pair with the code
the console shows, and use the full interface, including **Add a download link**. This is what the fork supports.

What you get and lose compared with Zero:

- **Works:** pasting a link from the Linux desktop's clipboard, picking the drive, the queue with pause, resume and
  retry, TorBox delivery, saved links, and the browser-assisted steps that finish on the PS5.
- **Different:** the PS5 downloads the file itself, over its own connection. Zero's route (download on the computer,
  then transfer) is not available for pasted links.
- **Not covered:** hosts that only a desktop browser can satisfy. Zero's Electron window lets a person pass a
  verification on the computer, but only for the four catalogue providers it knows (Vikingfile, AkiraBox, DataNodes,
  1Fichier) and only for catalogue releases. For FileDitch, Gofile and FuckingFast the fork offers no equivalent;
  TorBox is the route for the last two.

## What it would take to add this to Zero

A change by Zero's maintainer: a link field calling `POST /api/v1/custom/resolve`, then `POST /api/v1/downloads` with
the returned release id, and no assumption that every release id comes from the catalogue. The fork's API is
documented in `docs/custom-catalogue.md` and `backend/api.c`. Until then, the browser interface is the way in.
