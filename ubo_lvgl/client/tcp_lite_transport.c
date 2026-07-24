#include "tcp_lite_transport.h"

#ifdef ESP_PLATFORM
#include "lwip/netdb.h"
#include "lwip/sockets.h"
#else
#include <netdb.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

/* Matches http_transport.c's CURLOPT_CONNECTTIMEOUT for the grpc-web sibling:
 * a dead-but-routable host must not stall the caller for the OS/lwIP default
 * SYN timeout (tens of seconds) on every reconnect attempt. */
#define UBO_TCP_LITE_CONNECT_TIMEOUT_SEC 5

/* Connect fd with a bounded deadline instead of a plain blocking connect().
 * Returns 0 on success (fd left in blocking mode), -1 on failure/timeout. */
static int connect_with_timeout(int fd, const struct sockaddr *addr,
                                 socklen_t addrlen) {
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) {
        return -1;
    }

    int rc = connect(fd, addr, addrlen);
    if (rc == 0) {
        fcntl(fd, F_SETFL, flags); /* restore blocking mode */
        return 0;
    }
    if (errno != EINPROGRESS) {
        return -1;
    }

    fd_set wfds;
    FD_ZERO(&wfds);
    FD_SET(fd, &wfds);
    struct timeval tv = {.tv_sec = UBO_TCP_LITE_CONNECT_TIMEOUT_SEC, .tv_usec = 0};
    rc = select(fd + 1, NULL, &wfds, NULL, &tv);
    if (rc <= 0) {
        return -1; /* timeout (0) or select error (<0) */
    }

    int so_error = 0;
    socklen_t so_error_len = sizeof(so_error);
    if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &so_error, &so_error_len) < 0 ||
        so_error != 0) {
        return -1;
    }

    if (fcntl(fd, F_SETFL, flags) < 0) { /* restore blocking mode */
        return -1;
    }
    return 0;
}

/* Suppress SIGPIPE on a peer-closed write: Linux uses the MSG_NOSIGNAL send
 * flag, macOS/BSD the SO_NOSIGPIPE socket option; lwIP has no signals. */
#ifdef MSG_NOSIGNAL
#define UBO_TCP_LITE_SEND_FLAGS MSG_NOSIGNAL
#else
#define UBO_TCP_LITE_SEND_FLAGS 0
#endif

struct ubo_tcp_lite {
    int fd;
    uint8_t rbuf[2048]; /* heap-backed recv scratch: keeps caller stacks small */
};

ubo_tcp_lite *ubo_tcp_lite_connect(const char *host_port) {
    if (!host_port) {
        return NULL;
    }
    /* Split on the LAST ':' — plain hostname/IPv4 literal only. */
    const char *colon = strrchr(host_port, ':');
    if (!colon || colon == host_port || !colon[1]) {
        return NULL;
    }
    size_t hlen = (size_t)(colon - host_port);
    char host[256];
    if (hlen >= sizeof(host)) {
        return NULL;
    }
    memcpy(host, host_port, hlen);
    host[hlen] = '\0';
    const char *port = colon + 1;

    struct addrinfo hints;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    struct addrinfo *res = NULL;
    if (getaddrinfo(host, port, &hints, &res) != 0 || !res) {
        return NULL;
    }

    int fd = -1;
    for (struct addrinfo *ai = res; ai; ai = ai->ai_next) {
        fd = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (fd < 0) {
            continue;
        }
        if (connect_with_timeout(fd, ai->ai_addr, ai->ai_addrlen) == 0) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(res);
    if (fd < 0) {
        return NULL;
    }

#ifdef SO_NOSIGPIPE
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one));
#endif
    /* ~1s recv timeout so read_loop polls *stop even on a silent peer. */
    struct timeval tv = {.tv_sec = 1, .tv_usec = 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    ubo_tcp_lite *t = calloc(1, sizeof(*t));
    if (!t) {
        close(fd);
        return NULL;
    }
    t->fd = fd;
    return t;
}

void ubo_tcp_lite_close(ubo_tcp_lite *t) {
    if (!t) {
        return;
    }
    if (t->fd >= 0) {
        close(t->fd);
    }
    free(t);
}

int ubo_tcp_lite_write(ubo_tcp_lite *t, const uint8_t *data, size_t len) {
    if (!t) {
        return -1;
    }
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = send(t->fd, data + sent, len - sent, UBO_TCP_LITE_SEND_FLAGS);
        if (n > 0) {
            sent += (size_t)n;
        } else if (n < 0 &&
                   (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
            continue;
        } else {
            return -1;
        }
    }
    return 0;
}

int ubo_tcp_lite_read_loop(ubo_tcp_lite *t, ubo_tcp_lite_chunk_cb on_chunk,
                           void *user, volatile bool *stop) {
    if (!t) {
        return -1;
    }
    for (;;) {
        if (stop && *stop) {
            return 0;
        }
        ssize_t n = recv(t->fd, t->rbuf, sizeof(t->rbuf), 0);
        if (n > 0) {
            if (on_chunk && !on_chunk(user, t->rbuf, (size_t)n)) {
                return -1; /* callback abort (done, or poisoned stream) */
            }
        } else if (n == 0) {
            return 0; /* peer closed the stream cleanly */
        } else {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
                continue; /* recv timeout: re-check *stop and retry */
            }
            return -1; /* socket error */
        }
    }
}
