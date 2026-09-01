"""
Opt-in pagination: nothing changes shape until a caller asks for a page.

The blunt way to add pagination — a global DEFAULT_PAGINATION_CLASS with a
PAGE_SIZE — rewrites every list response from `[...]` to `{count, next,
previous, results}` in one deploy. Four screens read those lists as bare
arrays (the review queue, both social-account pickers, publishing history),
and the review queue computes its tab counts client-side over one unfiltered
fetch — so the failure mode is not a crash but silently wrong numbers and
silently empty pages.

So pagination is opt-in per request instead: without `?page_size=` a list
endpoint answers exactly as it always has, and with it the caller gets the
standard DRF envelope. Existing clients keep working untouched; new or heavy
callers can page. The default can be flipped endpoint-by-endpoint later, once
each endpoint's consumers are known to unwrap the envelope.
"""
from rest_framework.pagination import PageNumberPagination


class OptInPageNumberPagination(PageNumberPagination):
    #: None means "no page size unless the request names one", which DRF
    #: treats as "do not paginate" — the whole point of this class.
    page_size = None
    page_size_query_param = 'page_size'
    #: A ceiling so `?page_size=1000000` cannot un-do pagination's purpose.
    max_page_size = 200
