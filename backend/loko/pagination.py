from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Default page size 50, but the client may request the full list
    for a selected period via ?page_size=... (up to a high cap)."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 10000
