import unittest
from pathlib import Path

from turborefi.services.retrieval_service import RetrievalService


class RetrievalServiceTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_missing_guides_report_error(self):
        service = RetrievalService(
            repo_root=self.repo_root,
            fnma_index_dir=None,
            fhlmc_index_dir=None,
        )
        result = service.get_section(section_id="B3-3.1-01", gse="fnma")
        self.assertIn("error", result)
        self.assertIn("fnma", result["error"])

    def test_available_guides_empty_when_no_indices(self):
        service = RetrievalService(
            repo_root=self.repo_root,
            fnma_index_dir=None,
            fhlmc_index_dir=None,
        )
        self.assertEqual(service.available_guides(), [])

    def test_single_family_fhlmc_traversal_and_non_leaf_get_section(self):
        service = RetrievalService(
            repo_root=self.repo_root,
            fnma_index_dir=self.repo_root / "retrival" / "output" / "selling_guide_preprocessed",
            fhlmc_index_dir=self.repo_root / "retrival" / "output" / "sf_guide_index",
        )

        self.assertIn("fhlmc", service.available_guides())

        root = service.list_contents(gse="fhlmc", path=None)
        self.assertEqual(root[0]["id"], "guide_root")

        selling = service.list_contents(gse="fhlmc", path="guide_root")
        self.assertTrue(any(entry["id"] == "Selling" for entry in selling))

        origination = service.list_contents(gse="fhlmc", path="Selling")
        self.assertTrue(any(entry["id"] == "5000" for entry in origination))

        income = service.list_contents(gse="fhlmc", path="5000")
        self.assertTrue(any(entry["id"] == "5300" for entry in income))

        non_leaf = service.get_section(section_id="5300", gse="fhlmc")
        self.assertIn("children", non_leaf)
        self.assertTrue(any(child["id"] == "5302" for child in non_leaf["children"]))

        leaf = service.get_section(section_id="5302.2", gse="fhlmc")
        self.assertEqual(leaf["section_id"], "5302.2")
        self.assertIn("documentation", leaf["title"].lower())


if __name__ == "__main__":
    unittest.main()
