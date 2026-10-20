/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Test aid for tools/fork/audit-writes.sh: an LD_PRELOAD shim that logs every path-based filesystem
 * mutation a process asks libc for (tab-separated: operation, absolute path). Not part of any build. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static void logline(const char *op, int dirfd, const char *path, const char *path2) {
    const char *file = getenv("WRLOG_FILE");
    if (!file || !path) return;
    char base[PATH_MAX] = "", full[PATH_MAX * 2], proc[64];
    if (path[0] != '/') {
        if (dirfd == AT_FDCWD) { if (!getcwd(base, sizeof base)) strcpy(base, "?"); }
        else { snprintf(proc, sizeof proc, "/proc/self/fd/%d", dirfd); ssize_t n = readlink(proc, base, sizeof base - 1); base[n > 0 ? n : 0] = 0; }
    }
    snprintf(full, sizeof full, "%s%s%s", base, base[0] ? "/" : "", path);
    int saved = errno;
    int fd = (int)syscall(SYS_openat, AT_FDCWD, file, O_WRONLY | O_APPEND | O_CREAT, 0644);
    if (fd >= 0) { dprintf(fd, "%s\t%s\t%s\n", op, full, path2 ? path2 : ""); close(fd); }
    errno = saved;
}
static int writes(int flags) { return (flags & (O_WRONLY | O_RDWR | O_CREAT | O_TRUNC | O_APPEND)) != 0; }

typedef long (*fn5)(long, long, long, long, long);
#define REAL(name) ({ static void *r_; if (!r_) r_ = dlsym(RTLD_NEXT, name); (fn5)r_; })
#define L(x) ((long)(x))
#define OPEN_BODY(name, dirfd, path) \
    int mode = 0; if (flags & O_CREAT) { va_list a; va_start(a, flags); mode = va_arg(a, int); va_end(a); } \
    if (writes(flags)) logline(name, dirfd, path, NULL);
int open(const char *path, int flags, ...) { OPEN_BODY("open", AT_FDCWD, path) return (int)REAL("open")(L(path), L(flags), L(mode), 0, 0); }
int open64(const char *path, int flags, ...) { OPEN_BODY("open", AT_FDCWD, path) return (int)REAL("open64")(L(path), L(flags), L(mode), 0, 0); }
int openat(int d, const char *path, int flags, ...) { OPEN_BODY("openat", d, path) return (int)REAL("openat")(L(d), L(path), L(flags), L(mode), 0); }
int openat64(int d, const char *path, int flags, ...) { OPEN_BODY("openat", d, path) return (int)REAL("openat64")(L(d), L(path), L(flags), L(mode), 0); }
int creat(const char *path, mode_t m) { logline("creat", AT_FDCWD, path, NULL); return (int)REAL("creat")(L(path), L(m), 0, 0, 0); }
int mkdir(const char *p, mode_t m) { logline("mkdir", AT_FDCWD, p, NULL); return (int)REAL("mkdir")(L(p), L(m), 0, 0, 0); }
int mkdirat(int d, const char *p, mode_t m) { logline("mkdir", d, p, NULL); return (int)REAL("mkdirat")(L(d), L(p), L(m), 0, 0); }
int rename(const char *a, const char *b) { logline("rename-from", AT_FDCWD, a, NULL); logline("rename-to", AT_FDCWD, b, NULL); return (int)REAL("rename")(L(a), L(b), 0, 0, 0); }
int renameat(int d1, const char *a, int d2, const char *b) { logline("rename-from", d1, a, NULL); logline("rename-to", d2, b, NULL); return (int)REAL("renameat")(L(d1), L(a), L(d2), L(b), 0); }
int unlink(const char *p) { logline("unlink", AT_FDCWD, p, NULL); return (int)REAL("unlink")(L(p), 0, 0, 0, 0); }
int unlinkat(int d, const char *p, int f) { logline("unlink", d, p, NULL); return (int)REAL("unlinkat")(L(d), L(p), L(f), 0, 0); }
int rmdir(const char *p) { logline("rmdir", AT_FDCWD, p, NULL); return (int)REAL("rmdir")(L(p), 0, 0, 0, 0); }
int link(const char *a, const char *b) { logline("link", AT_FDCWD, b, NULL); return (int)REAL("link")(L(a), L(b), 0, 0, 0); }
int linkat(int d1, const char *a, int d2, const char *b, int f) { logline("link", d2, b, NULL); return (int)REAL("linkat")(L(d1), L(a), L(d2), L(b), L(f)); }
int symlink(const char *a, const char *b) { logline("symlink", AT_FDCWD, b, NULL); return (int)REAL("symlink")(L(a), L(b), 0, 0, 0); }
int truncate(const char *p, off_t l) { logline("truncate", AT_FDCWD, p, NULL); return (int)REAL("truncate")(L(p), L(l), 0, 0, 0); }
int chmod(const char *p, mode_t m) { logline("chmod", AT_FDCWD, p, NULL); return (int)REAL("chmod")(L(p), L(m), 0, 0, 0); }
FILE *fopen(const char *p, const char *m) { if (strpbrk(m, "wa+")) logline("fopen", AT_FDCWD, p, NULL); return (FILE *)REAL("fopen")(L(p), L(m), 0, 0, 0); }
FILE *fopen64(const char *p, const char *m) { if (strpbrk(m, "wa+")) logline("fopen", AT_FDCWD, p, NULL); return (FILE *)REAL("fopen64")(L(p), L(m), 0, 0, 0); }
