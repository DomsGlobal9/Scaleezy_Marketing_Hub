"""
Client-facing universal endpoints, under /api/marketing/ with the NORMAL
tenant permissions. Nothing here is cross-tenant.

    POST /api/marketing/brands/<brand>/notes/                natural-language note -> proposal cards
    POST /api/marketing/brands/<brand>/notes/<note>/accept/  accept one card
    GET  /api/marketing/inspirations/library/                the Scaleezy library (respects opt-out)
    POST /api/marketing/inspirations/library/<id>/adopt/     copy into the brand's own inspirations
    POST /api/marketing/brands/<brand>/enrich/               own-site enrichment run
"""
urlpatterns = []
