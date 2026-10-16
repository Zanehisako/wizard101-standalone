#ifndef W101_STEAM_BRIDGE_H
#define W101_STEAM_BRIDGE_H
#include <stdint.h>
#include <stddef.h>
typedef struct W101Steam W101Steam;
/* No SDK or Steam library is redistributed. Resolve the installed Mac client. */
int w101_steam_open(const char *library, W101Steam **out);
/* 0 connecting/waiting, 1 ticket ready, negative on failure. The caller must
   pump repeatedly with a cancellation check and deadline. Ticket is raw binary. */
int w101_steam_poll(W101Steam *steam, uint64_t *user, uint8_t *ticket, size_t capacity, size_t *length);
void w101_steam_close(W101Steam *steam);
#endif
