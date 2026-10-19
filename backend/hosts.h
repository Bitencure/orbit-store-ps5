#ifndef ORBIT_HOSTS_H
#define ORBIT_HOSTS_H
#include <stdbool.h>
#include <stddef.h>

/* File-host adapter table (fork). One row per provider, matched by real domain
 * only; labels and aliases are never used to classify a URL. */
typedef enum {
    HOST_WEB,      /* Generic HTTPS file: any public DNS name, direct download. */
    HOST_DIRECT,   /* Known host serving the file directly; transfers limited to its domains. */
    HOST_BROWSER,  /* Needs the PS5 browser flow (verification); handled by browser.c. */
    HOST_DISABLED  /* Recognised, but no verified download flow: refuse with a reason. */
} HostKind;

typedef struct {
    const char *id;               /* Matches Release.source and the Sources setting. */
    const char *label;            /* Shown to the user. */
    const char *aliases;          /* Space-separated search aliases; display only. */
    const char *const *domains;   /* Each entry matches itself and its subdomains. */
    HostKind kind;
    unsigned flag;                /* ORBIT_SOURCE_* bit, 0 when the host has no toggle. */
    const char *note;             /* Reason shown when kind == HOST_DISABLED. */
} HostAdapter;

const HostAdapter *host_by_id(const char *id);
/* Adapter whose domain list matches the URL's host; the generic web adapter for any
 * other valid public HTTPS URL; NULL when the URL itself is not acceptable. */
const HostAdapter *host_for_url(const char *url);
bool host_domain_match(const HostAdapter *host, const char *name);
size_t host_count(void);
const HostAdapter *host_at(size_t index);

/* Public DNS name: letters, digits and hyphens in dot-separated labels, a non-numeric
 * last label. IP literals, single labels and anything with userinfo are rejected. */
bool host_name_ok(const char *name);
/* https on 443 (loopback http in the test build), no userinfo or fragment, bounded
 * length, no control characters. Writes the lower-case host name when out is given. */
bool host_url_ok(const char *url, char *name, size_t cap);
/* Canonical page URL: other 1fichier domains map to 1fichier.com. Returns false if unchanged. */
bool host_canonical_url(const char *url, char *out, size_t cap);

/* Strip directories and characters unsafe on exFAT/UFS, keep it valid UTF-8, <= cap-1 bytes. */
bool filename_sanitize(const char *in, char *out, size_t cap);
/* Percent-decode into out; false on a malformed escape, NUL or overflow. */
bool pct_decode(const char *in, size_t length, char *out, size_t cap);
/* filename*= (UTF-8) preferred over filename=; decoded but not sanitised. */
bool disposition_filename(const char *header, char *out, size_t cap);
/* Last path segment of a URL, decoded; false when empty. */
bool url_last_segment(const char *url, char *out, size_t cap);
#endif
