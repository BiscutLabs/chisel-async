// SPDX-License-Identifier: Apache-2.0
// POSIX getline compatibility for the unchanged svsim C++ command reader.
#ifdef _WIN32
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <sys/types.h>
#include <string.h>
static FILE *ca_svsim_freopen(const char *path, const char *mode, FILE *stream) {
  return freopen(strcmp(path, "/dev/null") == 0 ? "NUL" : path, mode, stream);
}
#define freopen ca_svsim_freopen
static ssize_t ca_svsim_getline(char **line, size_t *capacity, FILE *stream) {
  if (!line || !capacity || !stream) { errno = EINVAL; return -1; }
  size_t used = 0;
  int ch;
  while ((ch = fgetc(stream)) != EOF) {
    if (!*line || used + 1 >= *capacity) {
      size_t next = *line && *capacity ? *capacity * 2 : 128;
      if (next <= used + 1) { errno = ENOMEM; return -1; }
      char *grown = (char *)realloc(*line, next);
      if (!grown) { errno = ENOMEM; return -1; }
      *line = grown; *capacity = next;
    }
    (*line)[used++] = (char)ch;
    if (ch == '\n') break;
  }
  if (!used) return -1;
  (*line)[used] = '\0';
  return (ssize_t)used;
}
#define getline ca_svsim_getline
#endif
