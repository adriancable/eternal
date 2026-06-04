/*
 * init.c - Minimal init that sets up controlling terminal and runs shell
 *
 * This program:
 * 1. Runs as PID 1 (kernel entry point via rdinit=/sbin/init)
 * 2. Opens /dev/console as stdin/stdout/stderr
 * 3. Detects serial vs framebuffer console and sets TERM accordingly
 * 4. Forks and execs /bin/sh as a CHILD process
 * 5. Parent (PID 1) stays alive to reap zombies
 *
 * The shell runs as a child (not PID 1), so:
 * - SIGINT/SIGTERM work correctly (no PID 1 protection)
 * - Typing 'exit' just exits the shell, not the system
 * - Init terminates the VM if the shell exits
 */

#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/wait.h>

#ifndef TIOCSCTTY
#define TIOCSCTTY 0x540E
#endif




/* Linux device numbers: major 4, minor 0-63 = tty0-tty63 (virtual console)
 *                       major 4, minor 64+  = ttyS0+    (serial)           */
#define DEV_MAJOR(d) (((d) >> 8) & 0xff)
#define DEV_MINOR(d) ((d) & 0xff)

/* TIOCGDEV returns the dev_t of the real device behind /dev/console */
#ifndef TIOCGDEV
#define TIOCGDEV 0x80045432
#endif

int main(void) {
    int fd;
    pid_t pid;
    unsigned int devnum;
    const char *term = "linux";

    /* Close any inherited file descriptors */
    close(0);
    close(1);
    close(2);

    /* Open the console as fd 0 (stdin) */
    fd = open("/dev/console", O_RDWR);
    if (fd < 0) {
        _exit(1);
    }

    /* Detect console type: /dev/console itself is major 5 minor 1,
     * so we need TIOCGDEV to get the underlying device */
    if (ioctl(fd, TIOCGDEV, &devnum) == 0 && DEV_MAJOR(devnum) == 4 && DEV_MINOR(devnum) >= 64) {
        term = "xterm";
    }

    /* Make sure fd is 0 (stdin) */
    if (fd != 0) {
        dup2(fd, 0);
        close(fd);
    }

    /* Dup stdin to stdout and stderr */
    dup2(0, 1);
    dup2(0, 2);

    /* Become session leader and acquire controlling terminal */
    setsid();
    ioctl(0, TIOCSCTTY, 1);

    /* Build environment */
    char term_env[32] = "TERM=";
    {
        int i = 5;
        const char *p = term;
        while (*p) term_env[i++] = *p++;
        term_env[i] = '\0';
    }
    char *envp[] = {
        term_env,
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME=/root",
        NULL
    };

    /* vfork shell, wait for it, halt */
    pid = vfork();
    if (pid == 0) {
        /* Child: exec the shell with environment */
        execle("/bin/sh", "sh", "-l", NULL, envp);
        _exit(1);
    }

    /* Parent: wait for shell to exit, reaping any orphaned zombies along the way.
     * We loop on waitpid(-1) so that orphaned children reparented to us (PID 1)
     * are reaped instead of lingering as zombies. */
    {
        int status;
        pid_t w;
        for (;;) {
            w = waitpid(-1, &status, 0);
            if (w == pid)
                break;          /* shell exited */
            if (w == -1)
                break;          /* ECHILD (no children left) or fatal error */
            /* else: reaped an orphan, keep waiting */
        }
    }

    /* Exit the VM */
    __asm__(".word 0, 0, 0");
}
