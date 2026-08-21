#define _GNU_SOURCE

#include <errno.h>
#include <sys/syscall.h>
#include <unistd.h>

/*
 * RunPod can place containers on hosts whose seccomp profile returns EPERM
 * for close_range(2). GLib only falls back to its portable descriptor walk
 * when close_range() reports ENOSYS, so every XFCE/GIO application launch
 * otherwise fails before exec() with G_SPAWN_ERROR_FAILED.
 *
 * Keep the host security decision intact: the denied syscall is never
 * retried or bypassed. We only translate the compatibility errno so GLib can
 * use its existing per-descriptor close fallback.
 */
int close_range(unsigned int first, unsigned int last, int flags)
{
#ifdef SYS_close_range
    int result = (int) syscall(SYS_close_range, first, last, flags);

    if (result == -1 && errno == EPERM)
        errno = ENOSYS;

    return result;
#else
    (void) first;
    (void) last;
    (void) flags;
    errno = ENOSYS;
    return -1;
#endif
}
