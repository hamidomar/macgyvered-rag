import importlib.util
import unittest


AGNO_AVAILABLE = importlib.util.find_spec("agno") is not None
PYDANTIC_AVAILABLE = importlib.util.find_spec("pydantic") is not None


@unittest.skipUnless(AGNO_AVAILABLE and PYDANTIC_AVAILABLE, "requires agno and pydantic")
class UC1WorkflowTests(unittest.TestCase):
    def test_workflow_bootstraps(self):
        from turborefi.config import load_settings
        from turborefi.workflow import TurboRefiWorkflow

        workflow = TurboRefiWorkflow(settings=load_settings())
        self.assertIn("uc1_sarah_chen", workflow.list_cases())


if __name__ == "__main__":
    unittest.main()
