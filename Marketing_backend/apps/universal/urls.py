"""
Client-facing universal endpoints, under /api/marketing/ with the NORMAL
tenant permissions. Nothing here is cross-tenant.

    POST /api/marketing/brands/<brand>/notes/                natural-language note -> proposal cards
    POST /api/marketing/brands/<brand>/notes/<note>/accept/  accept one card
    GET  /api/marketing/inspirations/library/                the Scaleezy library (respects opt-out)
    POST /api/marketing/inspirations/library/<id>/adopt/     copy into the brand's own inspirations
    POST /api/marketing/brands/<brand>/enrich/               own-site enrichment run

Route order caveat: `scaleezy_backend/urls.py` includes `apps.inspirations.urls`
before this module, and its DefaultRouter detail route
(`^inspirations/(?P<pk>[^/.]+)/$`) claims `inspirations/library/` first with
pk='library'. Until that include order is swapped (or the inspirations viewset
narrows `lookup_value_regex` to a uuid), the list is ALSO served at
`universal/library/`, which nothing else claims; the adopt route has an extra
segment and is not shadowed. Both spellings resolve to the same view.
"""
from django.urls import path

from .views import (
    BrandEnrichView,
    BrandNoteAcceptView,
    BrandNoteView,
    InspirationAdoptView,
    InspirationLibraryView,
)

app_name = 'universal'

urlpatterns = [
    path('brands/<uuid:brand_id>/notes/', BrandNoteView.as_view(), name='brand_notes'),
    path(
        'brands/<uuid:brand_id>/notes/<uuid:note_id>/accept/',
        BrandNoteAcceptView.as_view(), name='brand_note_accept',
    ),
    path('brands/<uuid:brand_id>/enrich/', BrandEnrichView.as_view(), name='brand_enrich'),
    path('inspirations/library/', InspirationLibraryView.as_view(), name='library'),
    path(
        'inspirations/library/<uuid:inspiration_id>/adopt/',
        InspirationAdoptView.as_view(), name='library_adopt',
    ),
    # Unshadowed spellings of the two library routes (see module docstring).
    path('universal/library/', InspirationLibraryView.as_view(), name='library_alias'),
    path(
        'universal/library/<uuid:inspiration_id>/adopt/',
        InspirationAdoptView.as_view(), name='library_adopt_alias',
    ),
]
