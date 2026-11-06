#pragma once
#include <stddef.h>
#include <stdint.h>

namespace http_image_range {
struct Range { size_t first = 0, length = 0; bool partial = false; };
// A single RFC 9110 byte range. Reject multi-ranges and integer overflow.
inline bool parse(const char* header, size_t total, Range& result) {
  result = Range{}; result.length = total;
  if (!header || !*header) return total != 0;
  const char* prefix = "bytes=";
  for (; *prefix; ++prefix, ++header) if (*header != *prefix) return false;
  auto number = [](const char*& cursor, size_t& value) {
    if (*cursor < '0' || *cursor > '9') return false;
    value = 0;
    while (*cursor >= '0' && *cursor <= '9') {
      const unsigned digit = *cursor++ - '0';
      if (value > (SIZE_MAX - digit) / 10) return false;
      value = value * 10 + digit;
    }
    return true;
  };
  size_t first = 0, last = 0;
  if (*header == '-') {
    ++header;
    if (!number(header, last) || *header || !last || !total) return false;
    first = last >= total ? 0 : total - last; last = total - 1;
  } else {
    if (!number(header, first) || *header++ != '-' || first >= total) return false;
    if (!*header) last = total - 1;
    else if (!number(header, last) || *header || last < first) return false;
    if (last >= total) last = total - 1;
  }
  result.first = first; result.length = last - first + 1; result.partial = true;
  return true;
}
}
