from __future__ import annotations

from typing import Any


class FakeHierarchyRetrievalService:
    CONTENTS: dict[str, dict[str | None, list[dict[str, Any]]]] = {
        "fnma": {
            None: [
                {"id": "B", "title": "B, Origination Through Closing", "has_children": True},
            ],
            "B": [
                {"id": "B2", "title": "B2, Eligibility", "has_children": True},
                {"id": "B3", "title": "B3, Underwriting Borrowers", "has_children": True},
                {"id": "B4", "title": "B4, Underwriting Property", "has_children": True},
            ],
            "B2": [
                {"id": "B2-1", "title": "B2-1, Mortgage Eligibility", "has_children": True},
            ],
            "B2-1": [
                {"id": "B2-1.2", "title": "B2-1.2, LTV, CLTV, HCLTV, and Subordinate Financing", "has_children": True},
                {"id": "B2-1.3", "title": "B2-1.3, Loan Purpose", "has_children": True},
            ],
            "B2-1.2": [
                {"id": "B2-1.2-01", "title": "Loan-to-Value (LTV) Ratios", "has_children": False},
            ],
            "B2-1.3": [
                {"id": "B2-1.3-02", "title": "Limited Cash-Out Refinance Transactions", "has_children": False},
            ],
            "B3": [
                {"id": "B3-3", "title": "B3-3, Income Assessment", "has_children": True},
            ],
            "B3-3": [
                {"id": "B3-3.1", "title": "B3-3.1, Employment and Other Sources of Income", "has_children": True},
                {"id": "B3-3.2", "title": "B3-3.2, Self-Employment Income", "has_children": True},
                {"id": "B3-3.3", "title": "B3-3.3, Self-Employment Documentation Requirements for an Individual", "has_children": True},
            ],
            "B3-3.1": [
                {"id": "B3-3.1-01", "title": "General Income Information", "has_children": False},
                {"id": "B3-3.1-02", "title": "Standards for Employment Documentation", "has_children": False},
            ],
            "B3-3.2": [
                {"id": "B3-3.2-01", "title": "Underwriting Factors and Documentation for a Self-Employed Borrower", "has_children": False},
            ],
            "B3-3.3": [
                {"id": "B3-3.3-03", "title": "Income or Loss Reported on IRS Form 1040, Schedule C", "has_children": False},
            ],
            "B4": [
                {"id": "B4-1", "title": "B4-1, Property Assessment and Valuation", "has_children": True},
            ],
            "B4-1": [
                {"id": "B4-1.4", "title": "B4-1.4, Special Appraisal and Other Valuation Considerations", "has_children": True},
            ],
            "B4-1.4": [
                {"id": "B4-1.4-10", "title": "Value Acceptance", "has_children": False},
                {"id": "B4-1.4-11", "title": "Value Acceptance + Property Data", "has_children": False},
            ],
        },
        "fhlmc": {
            None: [
                {"id": "guide_root", "title": "Freddie Mac Single-Family Seller/Servicer Guide", "has_children": True},
            ],
            "guide_root": [
                {"id": "Selling", "title": "Selling", "has_children": True},
            ],
            "Selling": [
                {"id": "4000", "title": "Mortgage Eligibility", "has_children": True},
                {"id": "5000", "title": "Origination and Underwriting", "has_children": True},
            ],
            "4000": [
                {"id": "4200", "title": "General Mortgage Eligibility", "has_children": True},
                {"id": "4300", "title": "Loan Purpose", "has_children": True},
            ],
            "4200": [
                {"id": "4203", "title": "Loan-to-Value (LTV) Ratios and Maximum Loan Amounts", "has_children": True},
            ],
            "4203": [
                {"id": "4203.1", "title": "Loan-to-value (LTV), total LTV (TLTV) and maximum loan amounts", "has_children": False},
            ],
            "4300": [
                {"id": "4301", "title": "Refinance Mortgages", "has_children": True},
            ],
            "4301": [
                {"id": "4301.4", "title": "No cash-out refinance Mortgages", "has_children": False},
            ],
            "5000": [
                {"id": "5300", "title": "Stable Monthly Income and Asset Qualification Sources", "has_children": True},
                {"id": "5600", "title": "Property Eligibility and Valuation", "has_children": True},
            ],
            "5300": [
                {"id": "5301", "title": "General Requirements for All Stable Monthly Income and Asset Qualification Sources", "has_children": True},
                {"id": "5302", "title": "General Requirements for Documentation Used to Verify Employment and Income", "has_children": True},
                {"id": "5304", "title": "Employed Income", "has_children": True},
            ],
            "5301": [
                {"id": "5301.1", "title": "General requirements for all stable monthly income", "has_children": False},
            ],
            "5302": [
                {"id": "5302.2", "title": "Employed income documentation and verification requirements", "has_children": False},
            ],
            "5304": [
                {"id": "5304.1", "title": "Stable monthly income and documentation requirements for self-employed Borrowers", "has_children": False},
            ],
            "5600": [
                {"id": "5602", "title": "Collateral Representations and Warranties and Automated Collateral Evaluation", "has_children": True},
            ],
            "5602": [
                {"id": "5602.3", "title": "Automated collateral evaluation (ACE)", "has_children": False},
            ],
        },
    }

    SECTIONS: dict[str, dict[str, dict[str, Any]]] = {
        "fnma": {
            "B2-1.2-01": {
                "section_id": "B2-1.2-01",
                "title": "Loan-to-Value (LTV) Ratios",
                "text": "This section defines LTV ratios and eligibility limits for refinance transactions.",
            },
            "B2-1.3-02": {
                "section_id": "B2-1.3-02",
                "title": "Limited Cash-Out Refinance Transactions",
                "text": "This section defines limited cash-out refinance transactions and the transaction structure.",
            },
            "B3-3.1-01": {
                "section_id": "B3-3.1-01",
                "title": "General Income Information",
                "text": "This section explains income stability, continuity, and general income analysis requirements.",
            },
            "B3-3.1-02": {
                "section_id": "B3-3.1-02",
                "title": "Standards for Employment Documentation",
                "text": "This section explains employment documentation and verification requirements for salaried borrowers.",
            },
            "B3-3.2-01": {
                "section_id": "B3-3.2-01",
                "title": "Underwriting Factors and Documentation for a Self-Employed Borrower",
                "text": "This section covers underwriting factors and documentation for self-employed borrowers.",
            },
            "B3-3.3-03": {
                "section_id": "B3-3.3-03",
                "title": "Income or Loss Reported on IRS Form 1040, Schedule C",
                "text": "This section covers Schedule C income analysis for self-employed borrowers.",
            },
            "B4-1.4-10": {
                "section_id": "B4-1.4-10",
                "title": "Value Acceptance",
                "text": "This section explains value acceptance options for property valuation.",
            },
            "B4-1.4-11": {
                "section_id": "B4-1.4-11",
                "title": "Value Acceptance + Property Data",
                "text": "This section explains value acceptance and property data options for valuation.",
            },
        },
        "fhlmc": {
            "4203.1": {
                "section_id": "4203.1",
                "title": "Loan-to-value (LTV), total LTV (TLTV) and maximum loan amounts",
                "text": "This section explains LTV limits and maximum loan amounts for refinance transactions.",
            },
            "4301.4": {
                "section_id": "4301.4",
                "title": "No cash-out refinance Mortgages",
                "text": "This section covers no cash-out refinance mortgage requirements and transaction structure.",
            },
            "5301.1": {
                "section_id": "5301.1",
                "title": "General requirements for all stable monthly income",
                "text": "This section covers stable monthly income requirements and continuity expectations.",
            },
            "5302.2": {
                "section_id": "5302.2",
                "title": "Employed income documentation and verification requirements",
                "text": "This section covers employed income documentation and verification requirements.",
            },
            "5304.1": {
                "section_id": "5304.1",
                "title": "Stable monthly income and documentation requirements for self-employed Borrowers",
                "text": "This section covers self-employed income documentation requirements.",
            },
            "5602.3": {
                "section_id": "5602.3",
                "title": "Automated collateral evaluation (ACE)",
                "text": "This section covers automated collateral evaluation and property valuation support.",
            },
        },
    }

    REFERENCES: dict[str, dict[str, list[str]]] = {
        "fnma": {
            "B2-1.3-02": ["B2-1.2-01"],
            "B4-1.4-11": ["B4-1.4-10"],
        },
        "fhlmc": {
            "4301.4": ["4203.1"],
            "5602.3": ["4203.1"],
        },
    }

    def available_guides(self):
        return ["fhlmc", "fnma"]

    def list_contents(self, gse: str, path: str | None = None):
        guide = self.CONTENTS.get(gse)
        if guide is None:
            return [{"error": f"Guide not configured for {gse}"}]
        return guide.get(path, [])

    def get_section(self, section_id: str, gse: str):
        guide_sections = self.SECTIONS.get(gse)
        if guide_sections is None:
            return {"error": f"Guide not configured for {gse}"}
        section = guide_sections.get(section_id)
        if section is not None:
            return {
                **section,
                "references": self.REFERENCES.get(gse, {}).get(section_id, []),
                "cited_by": [],
            }
        children = self.CONTENTS.get(gse, {}).get(section_id)
        if children:
            return {
                "note": f"'{section_id}' is not a leaf section. Here are its children.",
                "children": children,
            }
        return {"error": f"Section '{section_id}' not found."}

    def search_titles(self, query: str, gse: str):
        guide_sections = self.SECTIONS.get(gse)
        if guide_sections is None:
            return [{"error": f"Guide not configured for {gse}"}]
        lowered_query = query.lower()
        results = []
        for section in guide_sections.values():
            haystack = f"{section['section_id']} {section['title']}".lower()
            if all(token in haystack for token in lowered_query.split()):
                results.append(
                    {
                        "section_id": section["section_id"],
                        "title": section["title"],
                    }
                )
        return results

    def get_section_with_references(self, section_id: str, gse: str, depth: int = 1):
        section = self.get_section(section_id, gse)
        if "error" in section:
            return section
        references = []
        for ref_id in self.REFERENCES.get(gse, {}).get(section_id, []):
            ref_section = self.get_section(ref_id, gse)
            if "error" not in ref_section:
                references.append(ref_section)
        sections = [section, *references]
        return {
            "primary": section_id,
            "sections": sections,
            "total_text_length": sum(len(entry.get("text", "")) for entry in sections),
        }
