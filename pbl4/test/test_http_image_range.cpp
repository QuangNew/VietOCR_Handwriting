#include "http_image_range.h"
#include <assert.h>
#include <stdio.h>
#include <initializer_list>
int main() {
  http_image_range::Range r;
  assert(http_image_range::parse(nullptr, 486862, r) && !r.partial && r.length == 486862);
  assert(http_image_range::parse("bytes=463801-", 486862, r) && r.first == 463801 && r.length == 23061);
  assert(http_image_range::parse("bytes=0-131071", 486862, r) && r.length == 131072);
  assert(http_image_range::parse("bytes=480000-999999", 486862, r) && r.length == 6862);
  assert(http_image_range::parse("bytes=-100", 486862, r) && r.first == 486762 && r.length == 100);
  for (auto invalid : {"bytes=486862-", "bytes=20-1", "bytes=0-1,4-5", "bytes=184467440737095516160-", "bytes=-0", "bytes=-", "bytes=", "bits=1-2"})
    assert(!http_image_range::parse(invalid, 486862, r));
  puts("HTTP image byte ranges PASS");
}
