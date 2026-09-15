"""Verify interfaces between independently packaged deployment components."""

import json
import os
from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ManifestTests(unittest.TestCase):
    def test_analysis_service_packages_shared_engine_without_local_artifacts(self):
        manifest = yaml.safe_load((ROOT / "azure.yaml").read_text())
        service = manifest["services"]["business-investigator"]
        source = ROOT / service["project"]
        self.assertEqual(source.resolve(), ROOT)
        self.assertTrue((source / service["codeConfiguration"]["entryPoint"]).is_file())
        self.assertTrue((source / "analysis" / "hosted-policy.json").is_file())
        self.assertIn("-r agent/requirements.txt", (source / "requirements.txt").read_text())
        ignored = (source / ".agentignore").read_text().splitlines()
        for path in (".azure/", ".artifacts/", ".venv/", ".git/", ".env", ".env.*"):
            self.assertIn(path, ignored)
        self.assertNotIn("analysis/", ignored)
        self.assertNotIn("agent/", ignored)
        self.assertEqual(service["protocols"], [{"protocol": "responses", "version": "2.0.0"}])

    def test_source_service_matches_runtime(self):
        manifest = yaml.safe_load((ROOT / "azure.yaml").read_text())
        service = manifest["services"]["sql-probe"]
        source = ROOT / service["project"]
        self.assertEqual(service["host"], "azure.ai.agent")
        self.assertEqual(service["kind"], "hosted")
        self.assertTrue((source / service["codeConfiguration"]["entryPoint"]).is_file())
        self.assertTrue((source / "requirements.txt").is_file())
        self.assertEqual(service["codeConfiguration"]["runtime"], "python_3_13")
        self.assertEqual(service["codeConfiguration"]["dependencyResolution"], "remote_build")
        self.assertEqual(service["protocols"], [{"protocol": "responses", "version": "2.0.0"}])
        variables = {entry["name"]: entry["value"] for entry in service["environmentVariables"]}
        for name in ["AZURE_SQL_SERVER", "AZURE_SQL_DATABASE", "AZURE_AI_MODEL_DEPLOYMENT_NAME",
                     "AZURE_AI_MODEL_ENDPOINT", "AZURE_AI_MODEL_API"]:
            self.assertEqual(variables[name], "${" + name + "}")
        self.assertEqual(variables["APP_LOCAL_DEVELOPMENT"], "false")
        self.assertNotIn("AZURE_CLIENT_ID", variables)
        self.assertEqual(manifest["infra"]["provider"], "bicep")

    def test_documentation_links_resolve_locally(self):
        import re

        for document in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
            for target in re.findall(r"\]\(([^)]+)\)", document.read_text()):
                if "://" not in target and not target.startswith("#"):
                    self.assertTrue((document.parent / target.split("#")[0]).exists(),
                                    f"{document.name}: {target}")


@unittest.skipUnless(os.environ.get("BICEP_CLI"), "BICEP_CLI required for deployment interface checks")
class LifecycleBicepInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = {}
        for entry in ("main", "bootstrap"):
            result = subprocess.run(
                [os.environ["BICEP_CLI"], "build", str(ROOT / "infra-bicep" / f"{entry}.bicep"),
                 "--stdout"], capture_output=True, text=True, check=True,
            )
            cls.templates[entry] = json.loads(result.stdout)

    def test_lifecycle_supplies_every_required_parameter(self):
        supplied = {
            "main": {
                "environmentName", "location", "deploymentId", "modelName",
                "modelVersion", "modelSku", "modelCapacity", "operatorPrincipalId",
                "deploymentPrincipalType", "sqlAdminMode", "sqlAdminObjectId", "sqlAdminLogin",
                "deployModel", "modelEndpoint", "modelApi",
            },
            "bootstrap": {
                "environmentName", "location", "deploymentId",
                "agentPrincipalId", "agentClientId",
            },
        }
        for name, template in self.templates.items():
            parameters = template["parameters"]
            required = {key for key, value in parameters.items() if "defaultValue" not in value}
            self.assertLessEqual(required, supplied[name], f"{name}: required inputs missing")
            self.assertLessEqual(supplied[name], parameters.keys(), f"{name}: unsupported inputs")

    def test_lifecycle_export_outputs_exist(self):
        outputs = self.templates["main"]["outputs"]
        expected = {
            "AZURE_AI_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_NAME", "AZURE_AI_ACCOUNT_NAME",
            "AZURE_AI_PROJECT_ID", "AZURE_AI_MODEL_DEPLOYMENT_NAME",
            "AZURE_AI_MODEL_ENDPOINT", "AZURE_AI_MODEL_API",
            "AZURE_SQL_SERVER", "AZURE_SQL_DATABASE", "INITIALIZER_CLIENT_ID",
            "sqlServerId", "sqlServerName",
        }
        self.assertLessEqual(expected, outputs.keys())


if __name__ == "__main__":
    unittest.main()
