/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ORBIT_RESOLVE_H
#define ORBIT_RESOLVE_H
#include "hosts.h"
#include "orbit.h"

/* What one guarded probe learned about a link. Nothing here is a download URL the
 * queue trusts: transfers re-validate size, validators and every redirect hop. */
typedef struct {
    const HostAdapter *host;
    char url[2048];      /* The link as pasted (1fichier aliases canonicalised). */
    char filename[160];  /* Sanitised; from the user, Content-Disposition, then the URL. */
    char etag[256], modified[128];
    int64_t size;
    bool ranges;         /* The host honoured a byte range, so resume and splitting can work. */
} Resolved;

/* Blocking; call without orbit.mutex. Return 0, or -1 with a user-facing message. */
int resolve_direct(const HostAdapter *host, const char *url, const char *wanted_name,
                   atomic_bool *cancel, Resolved *out, char *error, size_t cap);
/* Vikingfile /f/<id> page: name and size from its public file listing. */
int resolve_viking(const char *page_url, atomic_bool *cancel, Resolved *out, char *error, size_t cap);
/* FileDitch's documented, open status endpoint: does the file exist, and how big is it? It cannot
 * be downloaded by a script (Cloudflare challenge), but its existence can be checked. Returns 1 exists,
 * 0 gone, -1 unknown; size is set when it exists. */
int resolve_fileditch_status(const char *url, atomic_bool *cancel, int64_t *size);
#endif
