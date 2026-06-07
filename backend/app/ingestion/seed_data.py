from __future__ import annotations

from datetime import date

SOURCES = [
    {
        "name": "People's Assembly",
        "base_url": "https://www.pa.org.za/",
        "source_type": "civic_profile",
        "reliability_score": 0.85,
    },
    {
        "name": "PMG",
        "base_url": "https://pmg.org.za/",
        "source_type": "parliamentary_monitoring",
        "reliability_score": 0.9,
    },
    {
        "name": "Parliament of South Africa",
        "base_url": "https://www.parliament.gov.za/",
        "source_type": "official",
        "reliability_score": 0.95,
    },
]

PARTIES = [
    {"name": "African National Congress", "short_name": "ANC", "website_url": "https://www.anc1912.org.za/"},
    {"name": "Democratic Alliance", "short_name": "DA", "website_url": "https://www.da.org.za/"},
    {"name": "Economic Freedom Fighters", "short_name": "EFF", "website_url": "https://effonline.org/"},
    {"name": "Inkatha Freedom Party", "short_name": "IFP", "website_url": "https://www.ifp.org.za/"},
    {"name": "Freedom Front Plus", "short_name": "FF+", "website_url": "https://www.vfplus.org.za/"},
    {"name": "United Democratic Movement", "short_name": "UDM", "website_url": "https://udm.org.za/"},
    {"name": "Good", "short_name": "GOOD", "website_url": "https://forgood.org.za/"},
    {"name": "Patriotic Alliance", "short_name": "PA", "website_url": "https://www.patrioticalliance.co.za/"},
]

COMMITTEES = [
    {"name": "National Assembly", "slug": "national-assembly", "description": "Lower house of Parliament."},
    {"name": "Finance", "slug": "finance", "description": "Oversight of fiscal and financial matters."},
    {"name": "Justice and Constitutional Development", "slug": "justice-and-constitutional-development", "description": "Justice portfolio oversight."},
    {"name": "Basic Education", "slug": "basic-education", "description": "Basic education portfolio oversight."},
    {"name": "Home Affairs", "slug": "home-affairs", "description": "Home affairs portfolio oversight."},
    {"name": "Defence and Military Veterans", "slug": "defence-and-military-veterans", "description": "Defence portfolio oversight."},
    {"name": "Tourism", "slug": "tourism", "description": "Tourism portfolio oversight."},
    {"name": "Sports, Arts and Culture", "slug": "sports-arts-and-culture", "description": "Culture and sport portfolio oversight."},
    {"name": "Cooperative Governance and Traditional Affairs", "slug": "cogta", "description": "Local governance portfolio oversight."},
    {"name": "Public Service and Administration", "slug": "public-service-and-administration", "description": "Public administration oversight."},
]

POLITICIANS = [
    {
        "full_name": "Matamela Cyril Ramaphosa",
        "display_name": "Cyril Ramaphosa",
        "slug": "cyril-ramaphosa",
        "party": "ANC",
        "profile_url": "https://www.pa.org.za/person/matamela-cyril-ramaphosa/",
        "committee": "national-assembly",
        "role": "Member",
    },
    {
        "full_name": "Julius Sello Malema",
        "display_name": "Julius Malema",
        "slug": "julius-malema",
        "party": "EFF",
        "profile_url": "https://www.pa.org.za/person/julius-sello-malema/",
        "committee": "finance",
        "role": "Member",
    },
    {
        "full_name": "John Henry Steenhuisen",
        "display_name": "John Steenhuisen",
        "slug": "john-steenhuisen",
        "party": "DA",
        "profile_url": "https://www.pa.org.za/person/john-henry-steenhuisen/",
        "committee": "national-assembly",
        "role": "Member",
    },
    {
        "full_name": "Siviwe Gwarube",
        "display_name": "Siviwe Gwarube",
        "slug": "siviwe-gwarube",
        "party": "DA",
        "profile_url": "https://www.pa.org.za/person/siviwe-gwarube/",
        "committee": "basic-education",
        "role": "Member",
    },
    {
        "full_name": "Velenkosini Fiki Hlabisa",
        "display_name": "Velenkosini Hlabisa",
        "slug": "velenkosini-hlabisa",
        "party": "IFP",
        "profile_url": "https://www.pa.org.za/person/velenkosini-fiki-hlabisa/",
        "committee": "home-affairs",
        "role": "Member",
    },
    {
        "full_name": "Pieter Mey Groenewald",
        "display_name": "Pieter Groenewald",
        "slug": "pieter-groenewald",
        "party": "FF+",
        "profile_url": "https://www.pa.org.za/person/pieter-mey-groenewald/",
        "committee": "defence-and-military-veterans",
        "role": "Member",
    },
    {
        "full_name": "Bantu Stephen Biko Holomisa",
        "display_name": "Bantu Holomisa",
        "slug": "bantu-holomisa",
        "party": "UDM",
        "profile_url": "https://www.pa.org.za/person/bantu-stephen-biko-holomisa/",
        "committee": "defence-and-military-veterans",
        "role": "Member",
    },
    {
        "full_name": "Patricia de Lille",
        "display_name": "Patricia de Lille",
        "slug": "patricia-de-lille",
        "party": "GOOD",
        "profile_url": "https://www.pa.org.za/person/patricia-de-lille/",
        "committee": "tourism",
        "role": "Member",
    },
    {
        "full_name": "Gayton McKenzie",
        "display_name": "Gayton McKenzie",
        "slug": "gayton-mckenzie",
        "party": "PA",
        "profile_url": "https://www.pa.org.za/person/gayton-mckenzie/",
        "committee": "sports-arts-and-culture",
        "role": "Member",
    },
    {
        "full_name": "Thembi Nkadimeng",
        "display_name": "Thembi Nkadimeng",
        "slug": "thembi-nkadimeng",
        "party": "ANC",
        "profile_url": "https://www.pa.org.za/person/thembi-nkadimeng/",
        "committee": "cogta",
        "role": "Member",
    },
]


def sample_document_for_politician(politician: dict[str, str]) -> dict[str, object]:
    slug = politician["slug"]
    display_name = politician["display_name"]
    return {
        "title": f"Sample parliamentary evidence note: {display_name}",
        "document_type": "sample_evidence_note",
        "source_name": "PMG",
        "source_url": f"https://pmg.org.za/committee-meeting/sample-knowyourmpza-{slug}/",
        "publication_date": date(2024, 7, 1),
        "raw_text": (
            f"KnowYourMPZA sample evidence note for {display_name}. "
            "This local seed document gives the MVP a stable evidence trail until live ingestion is enabled."
        ),
        "snippet": f"{display_name} appears in this seeded parliamentary evidence note with a source URL for demo verification.",
        "confidence_score": 1.0,
    }
