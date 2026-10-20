// SPDX-License-Identifier: GPL-3.0-or-later
// The default drive and the destination line in Add a download link (src/driveChoice.ts). Run with `npm test`.
import test from "node:test";
import assert from "node:assert/strict";
import { chooseDrive, destinationPath } from "../src/driveChoice.ts";

const internal = { id: "internal", external: false, path: "/data/homebrew" };
const usb0 = { id: "usb0", external: true, path: "/mnt/usb0/homebrew" };
const usb1 = { id: "usb1", external: true, path: "/mnt/usb1/homebrew" };

test("a mounted USB drive is the default when nothing was saved, as on a game's download page", () => {
  assert.equal(chooseDrive([usb0, internal], "").id, "usb0");
  assert.equal(chooseDrive([internal, usb0], undefined).id, "usb0");
});

test("a saved default drive wins over a USB drive, internal storage included", () => {
  assert.equal(chooseDrive([usb0, internal], "internal").id, "internal");
  assert.equal(chooseDrive([usb0, usb1, internal], "usb1").id, "usb1");
});

test("a saved default that is not mounted falls back to the normal order", () => {
  assert.equal(chooseDrive([usb0, internal], "usb1").id, "usb0");
  assert.equal(chooseDrive([internal], "usb0").id, "internal");
});

test("with no drives there is no choice", () => {
  assert.equal(chooseDrive([], "usb0"), undefined);
});

test("the destination is the full file path, or only the folder while the name is unknown", () => {
  assert.equal(destinationPath(usb0, "orbit-fork-test.bin", false), "/mnt/usb0/homebrew/orbit-fork-test.bin");
  assert.equal(destinationPath(internal, "  padded.bin ", false), "/data/homebrew/padded.bin");
  assert.equal(destinationPath(usb0, "ignored.bin", true), "/mnt/usb0/homebrew/");
  assert.equal(destinationPath(undefined, "x.bin", false), "");
});
