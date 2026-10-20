# Saved links and the link catalogue (fork)

Orbit's built-in game catalogue is encrypted, signed by upstream and updated from upstream. This fork
never modifies it. Instead you can keep your own list of links, which Orbit stores next to its queue
(`custom-catalogue.json` in its state folder) and checks only when you use one.

**Nothing in this feature supplies links.** An entry is a link you already have and are allowed to
download. Orbit does not guess, generate or look up links.

## Using it

- Browser interface: **Add a download link** (the link icon in Store; Settings in the other looks).
  Open **Saved links** to import, use or remove entries.
- Native app: **More settings → Add a download link** opens the browser version at that panel.
- A paired phone or computer works too: open `http://<ps5-ip>:34177/#add-url`.

Choosing a saved link runs the same check as pasting it, so a link that has expired or changed is
reported then, not trusted from the file.

## File format

```json
{
  "format": "orbit-custom-catalogue",
  "version": 1,
  "entries": [
    {
      "title": "A name you will recognise",
      "url": "https://downloads.example.org/files/example.bin",
      "titleId": "PPSA01234",
      "platform": "ps5",
      "format": "File",
      "filename": "example.bin",
      "sizeBytes": 1048576
    }
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `title` | yes | Shown in Saved links. Up to 127 characters, no control characters. |
| `url` | yes | A complete `https://` link on port 443. Other schemes, user names, fragments, IP addresses and non-public names are refused. |
| `titleId` | no | `PPSA` or `CUSA` plus five digits. Display only for now. |
| `platform` | no | `ps4` or `ps5`. |
| `format` | no | Free text label such as `exFAT`, `PKG`, `File`. Display only. |
| `filename` | no | Must already be safe: no folders, no `..`, no `: * ? " < > |`, at most 159 bytes. Otherwise the entry is refused, never silently rewritten. |
| `sizeBytes` | no | A whole number. Needed only for hosts whose page shows a name and size but no way to read them (see below). |

An import accepts up to 256 entries (the request is limited to 256 KB). Each entry is checked on its
own: valid ones are kept and every refused one comes back with its position and a reason. A bad entry
never blocks the others. **Add to saved links** merges by link (re-importing a link updates it in
place); **Replace saved links** starts the list again.

## What each host can do

Hosts are matched by their real domain. The short names you may see elsewhere (for example "Viki",
"Akia", "Dith", "Data") are not used to classify a link.

| Host | Pasted link behaviour |
|---|---|
| Any other `https://` file | Direct download after a one-request check. Pages, errors and redirects to unapproved hosts are refused. |
| Vikingfile | Name and size are read from Vikingfile's public file listing; the PS5 browser step captures the real link. |
| 1Fichier, DataNodes, AkiraBox | The PS5 browser step. Their pages show a name and size only to a person, so you enter both (`filename`, `sizeBytes`) or, where TorBox lists the host, use TorBox and skip that. |
| Gofile, FuckingFast | TorBox only. Orbit cannot fetch them itself (see the support matrix in `FORK.md`). |
| FileDitch, Rootz | Recognised and refused with the reason. |

## Safety rules that always apply

- Links are checked over HTTPS only; every redirect hop is checked again; the connection itself is
  refused if it would reach a private, loopback or link-local address.
- Pages (HTML, JSON, XML, text) are never saved as downloads.
- The size reported by the host must be known before a download is queued; a partial file resumes
  only when the host proves the file is the same (ETag or Last-Modified).
- A file is never written over an existing name.
